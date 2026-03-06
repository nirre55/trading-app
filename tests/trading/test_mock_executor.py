"""Tests pour MockExecutor — mode dry-run (Story 9.1)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.event_bus import EventBus
from src.models.events import CandleEvent, EventType, StrategyEvent, TradeEvent
from src.models.trade import TradeDirection
from src.trading.mock_executor import MockExecutor


def _make_strategy_config(pair: str = "BTC/USDT", rr: float = 2.0) -> MagicMock:
    cfg = MagicMock()
    cfg.pair = pair
    cfg.leverage = 5
    cfg.capital.risk_reward_ratio = rr
    cfg.capital.initial_balance = None  # Story 9.2 : pas de capital initial en config par défaut
    return cfg


def _make_capital_manager(qty: Decimal = Decimal("0.001")) -> MagicMock:
    mgr = MagicMock()
    mgr.calculate_position_size = MagicMock(return_value=qty)
    return mgr


def _make_connector(balance: Decimal = Decimal("1000")) -> MagicMock:
    from src.models.exchange import Balance
    conn = MagicMock()
    conn.pair = "BTC/USDT"
    conn.fetch_balance = AsyncMock(return_value=Balance(
        total=balance, free=balance, used=Decimal("0"), currency="USDT"
    ))
    return conn


def _make_trade_logger() -> MagicMock:
    lgr = MagicMock()
    lgr.log_trade = AsyncMock()
    return lgr


class TestMockExecutorInit:
    """Tests d'initialisation du MockExecutor."""

    def test_init_logs_dry_run_mode(self):
        """AC1 : Le log '[DRY-RUN] Mode simulation actif' est émis à l'initialisation."""
        from loguru import logger

        captured: list[str] = []
        handler_id = logger.add(lambda msg: captured.append(msg), level="INFO", format="{message}")
        try:
            MockExecutor(
                connector=_make_connector(),
                event_bus=EventBus(),
                config=_make_strategy_config(),
                capital_manager=_make_capital_manager(),
                trade_logger=_make_trade_logger(),
            )
        finally:
            logger.remove(handler_id)
        assert any("[DRY-RUN] Mode simulation actif" in m for m in captured)

    def test_init_subscribes_to_signals(self):
        """MockExecutor s'abonne aux signaux LONG/SHORT et CANDLE_CLOSED."""
        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )
        # Vérifier que les abonnements existent via les handlers bindés
        assert executor._handle_signal_long_bound is not None
        assert executor._handle_signal_short_bound is not None
        assert executor._handle_candle_bound is not None


class TestMockExecutorSignalHandling:
    """Tests de la gestion des signaux LONG/SHORT."""

    @pytest.mark.asyncio
    async def test_signal_long_emits_trade_opened(self):
        """AC2 : Signal LONG → TRADE_OPENED émis avec entry_price = signal_price."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 1
        ev = opened_events[0]
        assert ev.entry_price == Decimal("50000")
        assert ev.direction == TradeDirection.LONG.value

    @pytest.mark.asyncio
    async def test_signal_long_no_exchange_order_call(self):
        """AC2 : Aucun appel à connector.place_order() lors d'un signal LONG."""
        connector = _make_connector()
        connector.place_order = AsyncMock()
        connector.set_leverage = AsyncMock()

        event_bus = EventBus()
        executor = MockExecutor(
            connector=connector,
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        connector.place_order.assert_not_called()
        connector.set_leverage.assert_not_called()

    @pytest.mark.asyncio
    async def test_signal_short_emits_trade_opened(self):
        """AC2 : Signal SHORT → TRADE_OPENED émis avec direction SHORT."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_SHORT,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("51000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_SHORT, signal)

        assert len(opened_events) == 1
        assert opened_events[0].direction == TradeDirection.SHORT.value

    @pytest.mark.asyncio
    async def test_signal_ignored_when_missing_prices(self):
        """AC2 : Signal ignoré si signal_price ou sl_price manquant."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=None,
            sl_price=None,
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0

    @pytest.mark.asyncio
    async def test_signal_ignored_when_sl_distance_zero(self):
        """M4 : Signal ignoré si sl_distance == 0 (signal_price == sl_price)."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("50000"),  # sl_distance == 0
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0

    @pytest.mark.asyncio
    async def test_second_signal_same_pair_ignored(self):
        """M2 : Un deuxième signal sur la même paire est ignoré si un trade est déjà ouvert."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)
        # Deuxième signal — doit être ignoré (trade déjà ouvert)
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 1  # Seul le premier trade est ouvert


class TestMockExecutorTpSlDetection:
    """Tests de détection TP/SL sur CANDLE_CLOSED."""

    async def _open_long_trade(
        self,
        event_bus: EventBus,
        executor: MockExecutor,
        entry: Decimal = Decimal("50000"),
        sl: Decimal = Decimal("49000"),
    ) -> None:
        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=entry,
            sl_price=sl,
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

    @pytest.mark.asyncio
    async def test_sl_hit_long_emits_trade_closed(self):
        """AC3 : Pour un LONG, candle.low <= sl_price → TRADE_CLOSED émis."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        await self._open_long_trade(event_bus, executor, entry=Decimal("50000"), sl=Decimal("49000"))

        # Candle dont le low atteint le SL
        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("49500"),
            high=Decimal("49500"),
            low=Decimal("48900"),  # <= sl calculé
            close=Decimal("49200"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 1
        ev = closed_events[0]
        assert ev.pnl is not None
        assert ev.pnl < 0  # SL → perte

    @pytest.mark.asyncio
    async def test_tp_hit_long_emits_trade_closed(self):
        """AC3 : Pour un LONG, candle.high >= tp_price → TRADE_CLOSED émis."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        await self._open_long_trade(event_bus, executor, entry=Decimal("50000"), sl=Decimal("49000"))
        # entry=50000, sl=49000 → sl_distance=1000 → tp = 50000 + 2000 = 52000

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # >= tp=52000
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 1
        ev = closed_events[0]
        assert ev.pnl is not None
        assert ev.pnl > 0  # TP → gain

    @pytest.mark.asyncio
    async def test_no_close_when_price_between_sl_tp(self):
        """AC3 : Si le prix est entre SL et TP, le trade reste ouvert."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        await self._open_long_trade(event_bus, executor, entry=Decimal("50000"), sl=Decimal("49000"))

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("50500"),
            high=Decimal("51000"),  # < tp=52000
            low=Decimal("50200"),   # > sl=49000
            close=Decimal("50800"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 0

    @pytest.mark.asyncio
    async def test_sl_hit_short_emits_trade_closed(self):
        """AC3 : Pour un SHORT, candle.high >= sl_price → TRADE_CLOSED."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_SHORT,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("51000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_SHORT, signal)
        # entry=50000, sl=51000 → sl_distance=1000 → sl=50000+1000=51000, tp=50000-2000=48000

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("50500"),
            high=Decimal("51200"),  # >= sl=51000
            low=Decimal("50300"),
            close=Decimal("50600"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 1
        assert closed_events[0].pnl is not None
        assert closed_events[0].pnl < 0  # SL → perte

    @pytest.mark.asyncio
    async def test_tp_hit_short_emits_trade_closed(self):
        """AC3 : Pour un SHORT, candle.low <= tp_price → TRADE_CLOSED émis avec gain."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_SHORT,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("51000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_SHORT, signal)
        # entry=50000, sl=51000 → sl_distance=1000 → tp = 50000 - 2000 = 48000

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("49000"),
            high=Decimal("49000"),
            low=Decimal("47500"),  # <= tp=48000
            close=Decimal("48000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 1
        ev = closed_events[0]
        assert ev.pnl is not None
        assert ev.pnl > 0  # TP SHORT → gain

    @pytest.mark.asyncio
    async def test_trade_removed_after_close(self):
        """AC3 : Le trade est retiré des trades ouverts après fermeture."""
        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        await self._open_long_trade(event_bus, executor, entry=Decimal("50000"), sl=Decimal("49000"))
        assert len(executor._open_trades) == 1

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("49500"),
            high=Decimal("49500"),
            low=Decimal("48900"),
            close=Decimal("49200"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(executor._open_trades) == 0

    @pytest.mark.asyncio
    async def test_simulated_capital_updated_after_close(self):
        """M3 : La balance simulée est mise à jour après chaque clôture de trade."""
        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("1000")),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        await self._open_long_trade(event_bus, executor, entry=Decimal("50000"), sl=Decimal("49000"))
        assert executor._simulated_capital == Decimal("1000")

        # TP hit → pnl = (52000 - 50000) * 0.001 = 2.0
        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # >= tp=52000
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        # Balance simulée mise à jour : 1000 + (52000 - 50000) * 0.001 = 1002
        assert executor._simulated_capital == Decimal("1000") + (Decimal("52000") - Decimal("50000")) * Decimal("0.001")


class TestMockExecutorAC4:
    """AC4 : Endpoints d'ordre jamais appelés pendant tout le cycle dry-run."""

    @pytest.mark.asyncio
    async def test_no_order_endpoint_called_during_full_lifecycle(self):
        """AC4 : place_order et set_leverage jamais appelés — signal → TP → stop."""
        connector = _make_connector()
        connector.place_order = AsyncMock()
        connector.set_leverage = AsyncMock()

        event_bus = EventBus()
        executor = MockExecutor(
            connector=connector,
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        # Signal LONG → ouverture trade simulé
        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        # Candle qui déclenche le TP
        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # >= tp=52000
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        await executor.stop()

        connector.place_order.assert_not_called()
        connector.set_leverage.assert_not_called()


class TestMockExecutorCapitalFromConfig:
    """Tests AC1/AC2 (Story 9.2) : capital virtuel depuis config.capital.initial_balance."""

    def _make_strategy_config_with_initial_balance(
        self, initial_balance: Decimal, pair: str = "BTC/USDT", rr: float = 2.0
    ) -> MagicMock:
        cfg = MagicMock()
        cfg.pair = pair
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = rr
        cfg.capital.initial_balance = initial_balance
        return cfg

    def test_simulated_capital_initialise_depuis_config(self):
        """AC1 (Story 9.2) : _simulated_capital initialisé depuis initial_balance en config."""
        cfg = self._make_strategy_config_with_initial_balance(Decimal("1000"))
        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("5000")),  # balance exchange différente
            event_bus=EventBus(),
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )
        assert executor._simulated_capital == Decimal("1000")
        assert executor._initial_capital == Decimal("1000")

    def test_initial_capital_independant_de_la_balance_exchange(self):
        """AC1 : le sizing est basé sur initial_balance, pas sur la balance exchange."""
        cfg = self._make_strategy_config_with_initial_balance(Decimal("500"))
        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("9999")),
            event_bus=EventBus(),
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )
        assert executor._simulated_capital == Decimal("500")

    @pytest.mark.asyncio
    async def test_capital_mis_a_jour_apres_trade_ferme(self):
        """AC2 (Story 9.2) : capital virtuel mis à jour après chaque trade fermé."""
        cfg = self._make_strategy_config_with_initial_balance(Decimal("1000"), rr=2.0)
        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        # Ouvrir trade LONG (entry=50000, sl=49000)
        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        # TP hit → pnl = (52000 - 50000) * 0.001 = 2.0
        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # >= tp=52000
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        # Capital = 1000 + (52000 - 50000) * 0.001 = 1002
        expected = Decimal("1000") + (Decimal("52000") - Decimal("50000")) * Decimal("0.001")
        assert executor._simulated_capital == expected


class TestMockExecutorDryRunLog:
    """Tests AC3 (Story 9.2) : dry_run=True dans TradeResult loggé."""

    @pytest.mark.asyncio
    async def test_trade_result_logged_with_dry_run_true(self):
        """AC3 : le TradeResult passé à trade_logger.log_trade a dry_run=True."""
        event_bus = EventBus()
        trade_logger = _make_trade_logger()
        cfg = _make_strategy_config(rr=2.0)

        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("1000")),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=trade_logger,
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # TP hit
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        trade_logger.log_trade.assert_called_once()
        trade_result = trade_logger.log_trade.call_args[0][0]
        assert trade_result.dry_run is True


class TestMockExecutorCapitalEpuise:
    """Tests AC5 (Story 9.2) : capital virtuel épuisé → pas de trade."""

    @pytest.mark.asyncio
    async def test_capital_zero_no_trade_opened(self):
        """AC5 : capital <= 0 → TRADE_OPENED non émis."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("0")  # capital épuisé

        event_bus = EventBus()
        opened_events: list = []

        async def capture(event) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0

    @pytest.mark.asyncio
    async def test_capital_negatif_no_trade_opened(self):
        """AC5 : capital < 0 → TRADE_OPENED non émis."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("-50")  # capital négatif

        event_bus = EventBus()
        opened_events: list = []

        async def capture(event) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0

    @pytest.mark.asyncio
    async def test_capital_epuise_log_warn(self):
        """AC5 : capital <= 0 → message WARN '[WARN] Capital virtuel insuffisant...' loggé."""
        from loguru import logger

        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("0")

        event_bus = EventBus()
        captured: list[str] = []
        handler_id = logger.add(
            lambda msg: captured.append(msg), level="WARNING", format="{message}"
        )

        try:
            executor = MockExecutor(
                connector=_make_connector(),
                event_bus=event_bus,
                config=cfg,
                capital_manager=_make_capital_manager(),
                trade_logger=_make_trade_logger(),
            )

            signal = StrategyEvent(
                event_type=EventType.STRATEGY_SIGNAL_LONG,
                strategy_name="test",
                pair="BTC/USDT",
                signal_price=Decimal("50000"),
                sl_price=Decimal("49000"),
            )
            await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)
        finally:
            logger.remove(handler_id)

        assert any("Capital virtuel insuffisant" in m for m in captured)

    @pytest.mark.asyncio
    async def test_capital_sous_minimum_viable_no_trade_opened(self):
        """AC5 (H1-fix) : capital positif mais < 1 USDT → TRADE_OPENED non émis.

        Le guard couvre désormais 'capital < taille minimale de position', pas seulement <= 0.
        """
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("0.50")  # positif mais sous le minimum viable

        event_bus = EventBus()
        opened_events: list = []

        async def capture(event) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0

    @pytest.mark.asyncio
    async def test_capital_egal_minimum_viable_trade_autorise(self):
        """AC5 (H1-fix) : capital exactement égal à _MIN_VIABLE_CAPITAL → trade autorisé."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = MockExecutor._MIN_VIABLE_CAPITAL  # exactement 1 USDT

        event_bus = EventBus()
        opened_events: list = []

        async def capture(event) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 1


class TestMockExecutorSummary:
    """Tests AC6 (Story 9.2) : get_summary() retourne les bonnes valeurs."""

    def test_summary_initial_sans_trade(self):
        """AC6 : résumé sans trade — trades_count=0, pnl=0."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("1000")

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=EventBus(),
            config=cfg,
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )

        summary = executor.get_summary()
        assert summary["initial_capital"] == Decimal("1000")
        assert summary["final_capital"] == Decimal("1000")
        assert summary["pnl_total"] == Decimal("0")
        assert summary["trades_count"] == 0

    @pytest.mark.asyncio
    async def test_summary_apres_trade_gagnant(self):
        """AC6 : résumé après un trade TP — pnl positif, trades_count=1."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("1000")

        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        # TP hit → pnl = (52000 - 50000) * 0.001 = 2.0
        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        summary = executor.get_summary()
        assert summary["trades_count"] == 1
        assert summary["initial_capital"] == Decimal("1000")
        expected_pnl = (Decimal("52000") - Decimal("50000")) * Decimal("0.001")
        assert summary["pnl_total"] == expected_pnl
        assert summary["final_capital"] == Decimal("1000") + expected_pnl

    @pytest.mark.asyncio
    async def test_summary_trades_count_incremente(self):
        """AC6 : trades_count incrémenté à chaque clôture de trade."""
        cfg = MagicMock()
        cfg.pair = "BTC/USDT"
        cfg.leverage = 5
        cfg.capital.risk_reward_ratio = 2.0
        cfg.capital.initial_balance = Decimal("1000")

        event_bus = EventBus()
        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=cfg,
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        for _ in range(2):
            signal = StrategyEvent(
                event_type=EventType.STRATEGY_SIGNAL_LONG,
                strategy_name="test",
                pair="BTC/USDT",
                signal_price=Decimal("50000"),
                sl_price=Decimal("49000"),
            )
            await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

            candle = CandleEvent(
                event_type=EventType.CANDLE_CLOSED,
                pair="BTC/USDT",
                timeframe="1h",
                open=Decimal("51000"),
                high=Decimal("52500"),  # TP hit
                low=Decimal("51000"),
                close=Decimal("52000"),
                volume=Decimal("10"),
            )
            await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert executor.get_summary()["trades_count"] == 2


class TestMockExecutorAC4Notification:
    """AC4 (Story 9.2) : régression — TradeEvent émis avec préfixe [DRY-RUN] dans details."""

    @pytest.mark.asyncio
    async def test_trade_opened_event_details_prefixed_dry_run(self):
        """AC4 : details du TRADE_OPENED commence par '[DRY-RUN]' — contrat avec NotificationService."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("1000")),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 1
        assert opened_events[0].details is not None
        assert opened_events[0].details.startswith("[DRY-RUN]")

    @pytest.mark.asyncio
    async def test_trade_closed_event_details_prefixed_dry_run(self):
        """AC4 : details du TRADE_CLOSED commence par '[DRY-RUN]' — contrat avec NotificationService."""
        event_bus = EventBus()
        closed_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            closed_events.append(event)

        event_bus.on(EventType.TRADE_CLOSED, capture)

        executor = MockExecutor(
            connector=_make_connector(balance=Decimal("1000")),
            event_bus=event_bus,
            config=_make_strategy_config(rr=2.0),
            capital_manager=_make_capital_manager(Decimal("0.001")),
            trade_logger=_make_trade_logger(),
        )

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        candle = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("51000"),
            high=Decimal("52500"),  # TP hit
            low=Decimal("51000"),
            close=Decimal("52000"),
            volume=Decimal("10"),
        )
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)

        assert len(closed_events) == 1
        assert closed_events[0].details is not None
        assert closed_events[0].details.startswith("[DRY-RUN]")


class TestMockExecutorStop:
    """Tests du stop() et désabonnement."""

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_handlers(self):
        """stop() désabonne les handlers — plus de TRADE_OPENED après stop."""
        event_bus = EventBus()
        opened_events: list[TradeEvent] = []

        async def capture(event: TradeEvent) -> None:
            opened_events.append(event)

        event_bus.on(EventType.TRADE_OPENED, capture)

        executor = MockExecutor(
            connector=_make_connector(),
            event_bus=event_bus,
            config=_make_strategy_config(),
            capital_manager=_make_capital_manager(),
            trade_logger=_make_trade_logger(),
        )
        await executor.stop()

        signal = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="test",
            pair="BTC/USDT",
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
        )
        await event_bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

        assert len(opened_events) == 0
