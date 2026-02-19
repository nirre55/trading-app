"""Tests unitaires pour TradeExecutor — séquence atomique et invariant SL (NFR10)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.capital.base import BaseCapitalManager
from src.core.event_bus import EventBus
from src.core.exceptions import OrderFailedError, TradeError
from src.exchange.base import BaseExchangeConnector
from src.models.config import CapitalConfig, StrategyConfig
from src.models.events import EventType, StrategyEvent, TradeEvent
from src.models.exchange import Balance, MarketRules, OrderInfo, OrderSide, OrderStatus, OrderType
from src.models.trade import TradeDirection, TradeRecord, TradeResult, TradeStatus
from src.trading.trade_executor import TradeExecutor
from src.trading.trade_logger import TradeLogger


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_order(
    order_id: str = "ord-123",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    price: Decimal = Decimal("50000"),
    quantity: Decimal = Decimal("0.01"),
    status: OrderStatus = OrderStatus.FILLED,
    pair: str = "BTC/USDT",
) -> OrderInfo:
    return OrderInfo(
        id=order_id,
        pair=pair,
        side=side,
        order_type=order_type,
        price=price,
        quantity=quantity,
        status=status,
    )


def make_balance(free: str = "1000", used: str = "0") -> Balance:
    free_d = Decimal(free)
    used_d = Decimal(used)
    return Balance(total=free_d + used_d, free=free_d, used=used_d)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_config() -> StrategyConfig:
    """Config stratégie avec R:R=2.0, leverage=5, risk_percent=1.0."""
    return StrategyConfig(
        name="test-strategy",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=5,
        conditions=[],
        timeout_candles=10,
        capital=CapitalConfig(
            mode="fixed_percent",
            risk_percent=1.0,
            risk_reward_ratio=2.0,
        ),
    )


@pytest.fixture
def mock_connector() -> MagicMock:
    """Mock connecteur avec pair, market_rules, set_leverage et place_order configurés."""
    connector = MagicMock(spec=BaseExchangeConnector)
    connector.pair = "BTC/USDT"  # [M3] propriété publique
    connector.market_rules = MarketRules(
        step_size=Decimal("0.001"),
        tick_size=Decimal("0.1"),
        min_notional=Decimal("10"),
        max_leverage=10,
    )
    connector.set_leverage = AsyncMock()  # [FR14]
    # Comportement par défaut : entry FILLED + SL PENDING + TP PENDING
    connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    connector.fetch_positions = AsyncMock(return_value=[])
    connector.fetch_balance = AsyncMock(return_value=make_balance(free="10000"))
    return connector


@pytest.fixture
def mock_capital_manager() -> MagicMock:
    """6.1 : Mock de BaseCapitalManager retournant Decimal('0.01')."""
    manager = MagicMock(spec=BaseCapitalManager)
    manager.calculate_position_size.return_value = Decimal("0.01")
    return manager


@pytest.fixture
def mock_trade_logger() -> MagicMock:
    """4.1 : Mock de TradeLogger avec log_trade AsyncMock."""
    mock = MagicMock(spec=TradeLogger)
    mock.log_trade = AsyncMock()
    return mock


@pytest.fixture
def executor(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> TradeExecutor:
    """6.2 : Fixture executor avec capital_manager et trade_logger injectés."""
    return TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )


# ── Paramètres communs ────────────────────────────────────────────────────────


COMMON_PARAMS = {
    "pair": "BTC/USDT",
    "direction": TradeDirection.LONG,
    "quantity": Decimal("0.01"),
    "signal_price": Decimal("50000"),  # Story 4.2
    "sl_price": Decimal("49000"),
    "capital_before": Decimal("1000"),
}


# ── Tests AC1 + AC5 — Scénarios succès ───────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_success_returns_trade_record(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC1 + AC5 : séquence atomique succès → TradeRecord OPEN."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert result.status == TradeStatus.OPEN
    assert result.take_profit > Decimal(0)  # valeur réelle, non plus placeholder


@pytest.mark.asyncio
async def test_atomic_trade_success_emits_trade_opened(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC5 : séquence succès → événement TRADE_OPENED émis avec bon trade_id."""
    received_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        received_events.append(event)

    event_bus.on(EventType.TRADE_OPENED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.TRADE_OPENED
    assert received_events[0].trade_id == result.id
    assert received_events[0].pair == "BTC/USDT"


@pytest.mark.asyncio
async def test_atomic_trade_success_trade_record_fields(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC1 : vérification des champs du TradeRecord (direction, pair, quantity, entry_price)."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50500")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert result.pair == "BTC/USDT"
    assert result.direction == TradeDirection.LONG
    assert result.quantity == Decimal("0.01")
    assert result.entry_price == Decimal("50500")
    assert result.capital_before == Decimal("1000")
    assert result.leverage == 5  # depuis config (min(5, max_leverage=10))


# ── Tests AC2 — SL exception ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_sl_exception_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC2 : SL lève exception → position fermée immédiatement (3 appels place_order)."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),          # entry OK
            OrderFailedError("SL impossible"),               # SL lève exception
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),  # fermeture
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


@pytest.mark.asyncio
async def test_atomic_trade_sl_exception_emits_trade_failed(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC4 : SL exception → événement TRADE_FAILED émis."""
    received_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        received_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            OrderFailedError("SL impossible"),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.TRADE_FAILED
    assert received_events[0].pair == "BTC/USDT"


# ── Tests AC3 — SL statut FAILED/CANCELLED ────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_sl_failed_status_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC3 : SL retourne statut FAILED → position fermée."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.FAILED),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


@pytest.mark.asyncio
async def test_atomic_trade_sl_cancelled_status_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC3 : SL retourne statut CANCELLED → position fermée."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.CANCELLED),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


# ── Tests entrée échoue ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_entry_failure_no_close_attempt(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """Si l'entrée retourne FAILED, aucun ordre de fermeture n'est tenté (1 seul appel).

    AC4 : TRADE_FAILED est quand même émis — l'exception couvre toute la séquence.
    """
    failed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        failed_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        return_value=make_order(status=OrderStatus.FAILED)
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 1
    assert len(failed_events) == 1  # AC4 : TRADE_FAILED émis même quand entry échoue
    assert failed_events[0].event_type == EventType.TRADE_FAILED
    assert failed_events[0].pair == "BTC/USDT"


# ── Test retour None sur tout échec ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_returns_none_on_failure(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC4 : retour None ET TRADE_FAILED émis sur tout échec de la séquence atomique."""
    failed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        failed_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=RuntimeError("Erreur réseau inattendue")
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(failed_events) == 1  # AC4 : TRADE_FAILED émis sur exception inattendue
    assert failed_events[0].event_type == EventType.TRADE_FAILED


# ── Test fermeture impossible ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_close_failure_emits_error_critical(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """Si close échoue → ERROR_CRITICAL émis (position non protégée)."""
    critical_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        critical_events.append(event)

    event_bus.on(EventType.ERROR_CRITICAL, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),           # entry OK
            OrderFailedError("SL impossible"),                # SL échoue
            RuntimeError("Fermeture impossible"),             # close échoue aussi
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(critical_events) == 1
    assert critical_events[0].event_type == EventType.ERROR_CRITICAL
    assert "trade_id" in critical_events[0].message


# ── Test NFR10 — invariant SL ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "side_effects,expected_calls",
    [
        # Scénario 1 : SL exception → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                OrderFailedError("SL fail"),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
        # Scénario 2 : SL statut FAILED → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.FAILED),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
        # Scénario 3 : SL statut CANCELLED → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.CANCELLED),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
    ],
)
async def test_nfr10_all_trades_have_sl_or_are_closed(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
    side_effects: list,
    expected_calls: int,
) -> None:
    """NFR10 : 100% des trades ont SL actif OU position fermée — 0% non protégés."""
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )
    mock_connector.place_order = AsyncMock(side_effect=side_effects)

    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    # Dans tous les scénarios d'échec, position est fermée (None retourné)
    assert result is None
    # L'ordre de fermeture a été tenté
    assert mock_connector.place_order.call_count == expected_calls


# ── Test stop() — graceful shutdown ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_unsubscribes_from_bus(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> None:
    """Appeler stop() retire les handlers — les signaux suivants ne sont plus traités."""
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )

    # Vérifier que les handlers sont bien enregistrés avant stop()
    assert event_bus.has_handlers(EventType.STRATEGY_SIGNAL_LONG)
    assert event_bus.has_handlers(EventType.STRATEGY_SIGNAL_SHORT)

    await executor.stop()

    # Après stop(), les handlers doivent être retirés
    assert not event_bus.has_handlers(EventType.STRATEGY_SIGNAL_LONG)
    assert not event_bus.has_handlers(EventType.STRATEGY_SIGNAL_SHORT)
    assert not event_bus.has_handlers(EventType.TRADE_SL_HIT)
    assert not event_bus.has_handlers(EventType.TRADE_TP_HIT)


# ── Tests direction SHORT ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_short_success_uses_sell_entry(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> None:
    """H2 : direction SHORT → ordre d'entrée SELL et SL côté BUY."""
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(side=OrderSide.SELL, status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(side=OrderSide.BUY, order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(side=OrderSide.BUY, order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(
        pair="BTC/USDT",
        direction=TradeDirection.SHORT,
        quantity=Decimal("0.01"),
        signal_price=Decimal("50000"),
        sl_price=Decimal("51000"),
        capital_before=Decimal("1000"),
    )

    assert result is not None
    assert result.status == TradeStatus.OPEN
    assert result.direction == TradeDirection.SHORT
    # Vérifier que l'entrée est un SELL (direction SHORT)
    entry_call = mock_connector.place_order.call_args_list[0]
    assert entry_call.kwargs["side"] == OrderSide.SELL
    # Vérifier que le SL est un BUY (close_side pour SHORT)
    sl_call = mock_connector.place_order.call_args_list[1]
    assert sl_call.kwargs["side"] == OrderSide.BUY


@pytest.mark.asyncio
async def test_atomic_trade_short_sl_failure_closes_with_buy(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> None:
    """H2 : direction SHORT + SL exception → fermeture via ordre BUY (close_side inverse)."""
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(side=OrderSide.SELL, status=OrderStatus.FILLED),  # entry SELL
            OrderFailedError("SL impossible"),                             # SL échoue
            make_order(side=OrderSide.BUY, order_type=OrderType.MARKET),  # close BUY
        ]
    )
    result = await executor.execute_atomic_trade(
        pair="BTC/USDT",
        direction=TradeDirection.SHORT,
        quantity=Decimal("0.01"),
        signal_price=Decimal("50000"),
        sl_price=Decimal("51000"),
        capital_before=Decimal("1000"),
    )

    assert result is None
    assert mock_connector.place_order.call_count == 3
    # Vérifier que la fermeture utilise BUY (inverse du SELL d'entrée SHORT)
    close_call = mock_connector.place_order.call_args_list[2]
    assert close_call.kwargs["side"] == OrderSide.BUY


# ── Tests validation paramètres (M2) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_invalid_quantity_raises_value_error(
    executor: TradeExecutor,
) -> None:
    """M2 : quantity <= 0 lève ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="quantity doit être > 0"):
        await executor.execute_atomic_trade(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0"),
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
            capital_before=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_atomic_trade_invalid_sl_price_raises_value_error(
    executor: TradeExecutor,
) -> None:
    """M2 : sl_price <= 0 lève ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="sl_price doit être > 0"):
        await executor.execute_atomic_trade(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0.01"),
            signal_price=Decimal("50000"),
            sl_price=Decimal("0"),
            capital_before=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_atomic_trade_invalid_signal_price_raises_value_error(
    executor: TradeExecutor,
) -> None:
    """M2 : signal_price <= 0 lève ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="signal_price doit être > 0"):
        await executor.execute_atomic_trade(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0.01"),
            signal_price=Decimal("0"),
            sl_price=Decimal("49000"),
            capital_before=Decimal("1000"),
        )


# ── Tests Story 4.2 — Calcul TP/SL ───────────────────────────────────────────


def test_calculate_tp_sl_long_basic(executor: TradeExecutor) -> None:
    """AC1 : LONG — TP = entry + dist*rr, SL = entry - dist (sans arrondi)."""
    # signal_price=50000, sl_price=49000 → dist=1000, rr=2.0
    tp, sl = executor._calculate_tp_sl(
        TradeDirection.LONG,
        real_entry_price=Decimal("50200"),   # prix réel légèrement différent
        signal_price=Decimal("50000"),
        signal_sl_price=Decimal("49000"),
        risk_reward_ratio=Decimal("2.0"),
    )
    assert sl == Decimal("50200") - Decimal("1000")   # 49200
    assert tp == Decimal("50200") + Decimal("2000")   # 52200


def test_calculate_tp_sl_short_basic(executor: TradeExecutor) -> None:
    """AC1 : SHORT — TP = entry - dist*rr, SL = entry + dist."""
    # signal_price=50000, sl_price=51000 → dist=1000, rr=2.0
    tp, sl = executor._calculate_tp_sl(
        TradeDirection.SHORT,
        real_entry_price=Decimal("49900"),   # prix réel légèrement différent
        signal_price=Decimal("50000"),
        signal_sl_price=Decimal("51000"),
        risk_reward_ratio=Decimal("2.0"),
    )
    assert sl == Decimal("49900") + Decimal("1000")   # 50900
    assert tp == Decimal("49900") - Decimal("2000")   # 47900


def test_calculate_tp_sl_zero_distance_raises(executor: TradeExecutor) -> None:
    """signal_price == sl_price → ValueError (distance nulle invalide)."""
    with pytest.raises(ValueError, match="Distance SL invalide"):
        executor._calculate_tp_sl(
            TradeDirection.LONG,
            real_entry_price=Decimal("50000"),
            signal_price=Decimal("50000"),
            signal_sl_price=Decimal("50000"),  # même prix = invalide
            risk_reward_ratio=Decimal("2.0"),
        )


@pytest.mark.asyncio
async def test_execute_atomic_trade_recalculates_on_real_entry(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC2 : entry fills à 50200 (signal=50000, sl=49000) → TP/SL recalculés depuis 50200."""
    mock_connector.place_order = AsyncMock(side_effect=[
        make_order(status=OrderStatus.FILLED, price=Decimal("50200")),  # entry RÉEL à 50200
        make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
    ])
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    # SL recalculé : 50200 - 1000 = 49200 (pas 49000 du signal)
    # Après arrondi tick_size=0.1 : 49200.0
    assert result.stop_loss == Decimal("49200.0")
    # TP recalculé : 50200 + 2000 = 52200 → 52200.0
    assert result.take_profit == Decimal("52200.0")
    assert result.entry_price == Decimal("50200")
    # Vérifier que place_order SL a reçu le prix recalculé (pas sl_price=49000 du signal)
    sl_call = mock_connector.place_order.call_args_list[1]
    assert sl_call.kwargs["price"] == Decimal("49200.0")


@pytest.mark.asyncio
async def test_execute_atomic_trade_tp_sl_rounded_to_tick_size(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC3 : valeurs TP/SL arrondies au tick_size=0.1 (ROUND_HALF_UP)."""
    mock_connector.place_order = AsyncMock(side_effect=[
        make_order(status=OrderStatus.FILLED, price=Decimal("50000.33")),  # prix réel
        make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        make_order(order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
    ])
    # signal_price=50000, sl_price=49000 → dist=1000, real_entry=50000.33
    # raw_sl = 50000.33 - 1000 = 49000.33 → arrondi tick=0.1 → 49000.3
    # raw_tp = 50000.33 + 2000 = 52000.33 → arrondi tick=0.1 → 52000.3
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    # raw_sl = 50000.33 - 1000 = 49000.33 → ROUND_HALF_UP tick=0.1 → 49000.3
    # raw_tp = 50000.33 + 2000 = 52000.33 → ROUND_HALF_UP tick=0.1 → 52000.3
    assert result.stop_loss == Decimal("49000.3")
    assert result.take_profit == Decimal("52000.3")


@pytest.mark.asyncio
async def test_execute_atomic_trade_calls_set_leverage(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC4 : set_leverage appelé avec (pair, min(config.leverage, market_rules.max_leverage))."""
    await executor.execute_atomic_trade(**COMMON_PARAMS)

    # config.leverage=5, market_rules.max_leverage=10 → effective=5
    mock_connector.set_leverage.assert_called_once_with("BTC/USDT", 5)


@pytest.mark.asyncio
async def test_execute_atomic_trade_leverage_capped_at_max(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> None:
    """AC4 : config.leverage=15 > market_rules.max_leverage=10 → set_leverage(pair, 10)."""
    config_high_leverage = StrategyConfig(
        name="test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=15,   # dépasse le max exchange
        conditions=[],
        timeout_candles=10,
        capital=CapitalConfig(mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=2.0),
    )
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=config_high_leverage,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )
    await executor.execute_atomic_trade(**COMMON_PARAMS)

    # effective_leverage = min(15, 10) = 10
    mock_connector.set_leverage.assert_called_once_with("BTC/USDT", 10)


def test_base_connector_pair_property(mock_connector: MagicMock) -> None:
    """AC5 [M3] : BaseExchangeConnector expose pair comme @property publique."""
    # Vérifie que pair est un vrai @property sur la classe (pas un simple attribut)
    assert isinstance(BaseExchangeConnector.pair, property)
    # Vérifie l'accès via le Mock (spec=BaseExchangeConnector)
    assert mock_connector.pair == "BTC/USDT"


@pytest.mark.asyncio
async def test_execute_atomic_trade_rejects_wrong_pair(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC6 [M3] : pair passé ≠ connector.pair → ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="ne correspond pas"):
        await executor.execute_atomic_trade(
            pair="ETH/USDT",   # ≠ connector.pair = "BTC/USDT"
            direction=TradeDirection.LONG,
            quantity=Decimal("0.01"),
            signal_price=Decimal("3000"),
            sl_price=Decimal("2900"),
            capital_before=Decimal("1000"),
        )
    # Aucun appel réseau effectué
    mock_connector.set_leverage.assert_not_called()
    mock_connector.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_execute_atomic_trade_places_tp_order(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC1 + AC3 : 3 appels place_order sur succès, 3e = TAKE_PROFIT."""
    await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert mock_connector.place_order.call_count == 3
    tp_call = mock_connector.place_order.call_args_list[2]
    assert tp_call.kwargs["order_type"] == OrderType.TAKE_PROFIT
    assert tp_call.kwargs["side"] == OrderSide.SELL  # close_side pour LONG


@pytest.mark.asyncio
async def test_execute_atomic_trade_tp_failure_keeps_position_open(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """Échec TP = warning seulement, TradeRecord retourné (position protégée par SL)."""
    mock_connector.place_order = AsyncMock(side_effect=[
        make_order(status=OrderStatus.FILLED, price=Decimal("50000")),            # entry OK
        make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),   # SL OK
        RuntimeError("Exchange TP error"),                                          # TP échoue
    ])
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    # Position ouverte et protégée par SL — pas de fermeture sur échec TP
    assert result is not None
    assert result.status == TradeStatus.OPEN


@pytest.mark.asyncio
async def test_execute_atomic_trade_market_rules_none_raises(
    mock_connector: MagicMock,
    event_bus: EventBus,
    mock_config: StrategyConfig,
    mock_capital_manager: MagicMock,
    mock_trade_logger: MagicMock,
) -> None:
    """market_rules=None → TradeError avant tout appel réseau."""
    mock_connector.market_rules = None   # override : pas encore chargées
    executor = TradeExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=mock_config,
        capital_manager=mock_capital_manager,
        trade_logger=mock_trade_logger,
    )

    with pytest.raises(TradeError, match="market_rules non chargées"):
        await executor.execute_atomic_trade(**COMMON_PARAMS)

    mock_connector.set_leverage.assert_not_called()
    mock_connector.place_order.assert_not_called()


# ── Tests Story 4.3 — Signal handlers (AC4, AC7) ─────────────────────────────


@pytest.mark.asyncio
async def test_handle_signal_long_calls_fetch_balance_and_position_size(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    mock_capital_manager: MagicMock,
) -> None:
    """6.3 : _handle_signal_long → fetch_balance() + calculate_position_size() appelés."""
    event = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_LONG,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=Decimal("50000"),
        sl_price=Decimal("49000"),
    )
    await executor._handle_signal_long(event)  # type: ignore[arg-type]

    mock_connector.fetch_balance.assert_called_once()
    mock_capital_manager.calculate_position_size.assert_called_once_with(
        balance=Decimal("10000"),  # make_balance free=10000
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )


@pytest.mark.asyncio
async def test_handle_signal_long_calls_execute_atomic_trade_with_correct_args(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    mock_capital_manager: MagicMock,
) -> None:
    """6.3 : _handle_signal_long → execute_atomic_trade() avec capital_before, quantity, direction exacts."""
    mock_capital_manager.calculate_position_size.return_value = Decimal("0.01")
    event = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_LONG,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=Decimal("50000"),
        sl_price=Decimal("49000"),
    )

    with patch.object(executor, "execute_atomic_trade", new_callable=AsyncMock) as mock_eat:
        mock_eat.return_value = None
        await executor._handle_signal_long(event)  # type: ignore[arg-type]

        mock_eat.assert_called_once_with(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0.01"),          # issu du capital_manager
            signal_price=Decimal("50000"),
            sl_price=Decimal("49000"),
            capital_before=Decimal("10000"),   # issu de fetch_balance free=10000
        )


@pytest.mark.asyncio
async def test_handle_signal_short_calls_execute_with_direction_short(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    mock_capital_manager: MagicMock,
) -> None:
    """6.4 : _handle_signal_short → execute_atomic_trade() avec direction=SHORT."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(side=OrderSide.SELL, status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(side=OrderSide.BUY, order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
            make_order(side=OrderSide.BUY, order_type=OrderType.TAKE_PROFIT, status=OrderStatus.PENDING),
        ]
    )
    event = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_SHORT,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=Decimal("50000"),
        sl_price=Decimal("51000"),
    )
    await executor._handle_signal_short(event)  # type: ignore[arg-type]

    # Vérifier que l'entrée est un SELL (direction SHORT)
    entry_call = mock_connector.place_order.call_args_list[0]
    assert entry_call.kwargs["side"] == OrderSide.SELL


@pytest.mark.asyncio
async def test_handle_trade_closed_sl_hit_pnl_positive(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    event_bus: EventBus,
) -> None:
    """6.5 : _handle_trade_closed SL_HIT — capital_after > capital_before → pnl positif."""

    trade_id = "trade-abc"
    # Injecter un trade ouvert dans le registre interne
    executor._open_trades[trade_id] = TradeRecord(
        id=trade_id,
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        leverage=5,
        quantity=Decimal("0.01"),
        status=TradeStatus.OPEN,
        capital_before=Decimal("1000"),
    )
    # capital_after = 1050 > capital_before = 1000 → pnl = 50 (positif)
    mock_connector.fetch_balance = AsyncMock(return_value=make_balance(free="1050"))

    closed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        closed_events.append(event)

    event_bus.on(EventType.TRADE_CLOSED, capture)

    sl_event = TradeEvent(
        event_type=EventType.TRADE_SL_HIT,
        trade_id=trade_id,
        pair="BTC/USDT",
    )
    await executor._handle_trade_closed(sl_event)  # type: ignore[arg-type]

    assert len(closed_events) == 1
    assert closed_events[0].pnl == Decimal("50")  # 1050 - 1000
    assert closed_events[0].pnl > 0


@pytest.mark.asyncio
async def test_handle_trade_closed_tp_hit_pnl_negative(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    event_bus: EventBus,
) -> None:
    """6.6 : _handle_trade_closed TP_HIT — capital_after < capital_before → pnl négatif."""

    trade_id = "trade-xyz"
    executor._open_trades[trade_id] = TradeRecord(
        id=trade_id,
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        leverage=5,
        quantity=Decimal("0.01"),
        status=TradeStatus.OPEN,
        capital_before=Decimal("1000"),
    )
    # capital_after = 980 < capital_before = 1000 → pnl = -20 (négatif)
    mock_connector.fetch_balance = AsyncMock(return_value=make_balance(free="980"))

    closed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        closed_events.append(event)

    event_bus.on(EventType.TRADE_CLOSED, capture)

    tp_event = TradeEvent(
        event_type=EventType.TRADE_TP_HIT,
        trade_id=trade_id,
        pair="BTC/USDT",
    )
    await executor._handle_trade_closed(tp_event)  # type: ignore[arg-type]

    assert len(closed_events) == 1
    assert closed_events[0].pnl == Decimal("-20")  # 980 - 1000
    assert closed_events[0].pnl < 0


@pytest.mark.asyncio
async def test_handle_signal_long_ignores_missing_signal_price(
    executor: TradeExecutor,
    mock_connector: MagicMock,
) -> None:
    """Guard signal_price=None → retour silencieux, aucun appel réseau."""
    event = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_LONG,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=None,
        sl_price=Decimal("49000"),
    )
    await executor._handle_signal_long(event)  # type: ignore[arg-type]

    mock_connector.fetch_balance.assert_not_called()
    mock_connector.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_handle_signal_short_ignores_missing_sl_price(
    executor: TradeExecutor,
    mock_connector: MagicMock,
) -> None:
    """Guard sl_price=None → retour silencieux, aucun appel réseau."""
    event = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_SHORT,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=Decimal("50000"),
        sl_price=None,
    )
    await executor._handle_signal_short(event)  # type: ignore[arg-type]

    mock_connector.fetch_balance.assert_not_called()
    mock_connector.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_handle_trade_closed_unknown_trade_id_no_crash(
    executor: TradeExecutor,
    mock_connector: MagicMock,
) -> None:
    """_handle_trade_closed avec trade_id inconnu → warning silencieux, aucun appel réseau."""

    unknown_event = TradeEvent(
        event_type=EventType.TRADE_SL_HIT,
        trade_id="unknown-trade-id-xyz",
        pair="BTC/USDT",
    )
    # Ne doit pas lever d'exception
    await executor._handle_trade_closed(unknown_event)  # type: ignore[arg-type]

    mock_connector.fetch_balance.assert_not_called()


@pytest.mark.asyncio
async def test_handle_trade_closed_emits_capital_fields(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    event_bus: EventBus,
) -> None:
    """AC6 : TRADE_CLOSED émet capital_before et capital_after non nuls et corrects."""

    trade_id = "trade-capital-check"
    executor._open_trades[trade_id] = TradeRecord(
        id=trade_id,
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        leverage=5,
        quantity=Decimal("0.01"),
        status=TradeStatus.OPEN,
        capital_before=Decimal("1000"),
    )
    mock_connector.fetch_balance = AsyncMock(return_value=make_balance(free="1020"))

    closed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        closed_events.append(event)

    event_bus.on(EventType.TRADE_CLOSED, capture)

    tp_event = TradeEvent(
        event_type=EventType.TRADE_TP_HIT,
        trade_id=trade_id,
        pair="BTC/USDT",
    )
    await executor._handle_trade_closed(tp_event)  # type: ignore[arg-type]

    assert len(closed_events) == 1
    assert closed_events[0].capital_before == Decimal("1000")
    assert closed_events[0].capital_after == Decimal("1020")
    assert closed_events[0].pnl == Decimal("20")
    # Vérifier que TradeResult est stocké dans _closed_trades
    assert trade_id in executor._closed_trades
    assert executor._closed_trades[trade_id].capital_before == Decimal("1000")
    assert executor._closed_trades[trade_id].capital_after == Decimal("1020")


# ── Tests Story 4.4 — TradeLogger intégration (AC5) ──────────────────────────


@pytest.mark.asyncio
async def test_handle_trade_closed_calls_log_trade(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    mock_trade_logger: MagicMock,
    event_bus: EventBus,
) -> None:
    """AC5 : _handle_trade_closed → log_trade appelé avec le bon TradeResult (avant TRADE_CLOSED)."""

    trade_id = "trade-log-check"
    executor._open_trades[trade_id] = TradeRecord(
        id=trade_id,
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        leverage=5,
        quantity=Decimal("0.01"),
        status=TradeStatus.OPEN,
        capital_before=Decimal("1000"),
    )
    mock_connector.fetch_balance = AsyncMock(return_value=make_balance(free="1030"))

    sl_event = TradeEvent(
        event_type=EventType.TRADE_SL_HIT,
        trade_id=trade_id,
        pair="BTC/USDT",
    )
    await executor._handle_trade_closed(sl_event)  # type: ignore[arg-type]

    # Vérifier que log_trade a été appelé exactement une fois
    mock_trade_logger.log_trade.assert_called_once()

    # Vérifier que l'argument est bien un TradeResult avec les bonnes valeurs
    call_args = mock_trade_logger.log_trade.call_args
    logged_result = call_args[0][0]
    assert isinstance(logged_result, TradeResult)
    assert logged_result.trade_id == trade_id
    assert logged_result.pair == "BTC/USDT"
    assert logged_result.capital_before == Decimal("1000")
    assert logged_result.capital_after == Decimal("1030")
    assert logged_result.pnl == Decimal("30")


@pytest.mark.asyncio
async def test_handle_trade_closed_log_trade_called_before_trade_closed_emit(
    executor: TradeExecutor,
    mock_connector: MagicMock,
    mock_trade_logger: MagicMock,
    event_bus: EventBus,
) -> None:
    """AC5 : log_trade est appelé AVANT l'émission de TRADE_CLOSED — ordre critique (FR31)."""
    call_order: list[str] = []

    async def log_trade_side_effect(result: TradeResult) -> None:
        call_order.append("log_trade")

    mock_trade_logger.log_trade.side_effect = log_trade_side_effect

    async def on_trade_closed(event) -> None:  # type: ignore[no-untyped-def]
        call_order.append("trade_closed")

    event_bus.on(EventType.TRADE_CLOSED, on_trade_closed)  # type: ignore[arg-type]

    trade_id = "trade-order-check"
    executor._open_trades[trade_id] = TradeRecord(
        id=trade_id,
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit=Decimal("52000"),
        leverage=5,
        quantity=Decimal("0.01"),
        status=TradeStatus.OPEN,
        capital_before=Decimal("1000"),
    )
    mock_connector.fetch_balance = AsyncMock(return_value=make_balance(free="1030"))

    sl_event = TradeEvent(
        event_type=EventType.TRADE_SL_HIT,
        trade_id=trade_id,
        pair="BTC/USDT",
    )
    await executor._handle_trade_closed(sl_event)

    assert call_order == ["log_trade", "trade_closed"], (
        f"Ordre incorrect : {call_order} — log_trade DOIT précéder TRADE_CLOSED (AC5)"
    )
