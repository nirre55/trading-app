"""Tests pour le TradeSimulator — Story 5.2."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.backtest.trade_simulator import FEE_RATE, TradeSimulator
from src.core.event_bus import EventBus
from src.models.config import CapitalConfig, ConditionConfig, StrategyConfig
from src.models.events import CandleEvent, EventType, StrategyEvent
from src.models.trade import TradeDirection, TradeStatus


@pytest.fixture
def config() -> StrategyConfig:
    return StrategyConfig(
        name="test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[],
        timeout_candles=10,
        capital=CapitalConfig(mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=2.0),
    )


@pytest.fixture
def mock_capital_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.calculate_position_size.return_value = Decimal("0.1")
    return mgr


@pytest.fixture
def simulator(config: StrategyConfig, mock_capital_manager: MagicMock) -> TradeSimulator:
    bus = EventBus()
    return TradeSimulator(
        event_bus=bus,
        config=config,
        capital_manager=mock_capital_manager,
        initial_capital=Decimal("10000"),
    )


def _make_signal(
    direction: str,
    signal_price: Decimal,
    sl_price: Decimal,
    pair: str = "BTC/USDT",
) -> StrategyEvent:
    event_type = (
        EventType.STRATEGY_SIGNAL_LONG
        if direction == "LONG"
        else EventType.STRATEGY_SIGNAL_SHORT
    )
    return StrategyEvent(
        event_type=event_type,
        strategy_name="test",
        pair=pair,
        signal_price=signal_price,
        sl_price=sl_price,
    )


def _make_candle(
    low: Decimal,
    high: Decimal,
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    close: Decimal = Decimal("42000"),
) -> CandleEvent:
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair=pair,
        timeframe=timeframe,
        open=Decimal("42000"),
        high=high,
        low=low,
        close=close,
        volume=Decimal("10"),
    )


@pytest.mark.asyncio
async def test_signal_long_opens_trade(simulator: TradeSimulator) -> None:
    """Vérifie qu'un signal LONG crée un open_trade avec les bons champs."""
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    assert simulator._open_trade is not None
    assert simulator._open_trade.direction == TradeDirection.LONG
    assert simulator._open_trade.entry_price == Decimal("42000")
    assert simulator._open_trade.stop_loss == Decimal("41000")
    # TP = 42000 + 1000 * 2 = 44000
    assert simulator._open_trade.take_profit == Decimal("44000")
    assert simulator._open_trade.status == TradeStatus.OPEN
    assert simulator._open_trade.quantity == Decimal("0.1")


@pytest.mark.asyncio
async def test_signal_short_opens_trade(simulator: TradeSimulator) -> None:
    """Vérifie qu'un signal SHORT crée un open_trade avec direction SHORT."""
    signal = _make_signal("SHORT", Decimal("42000"), Decimal("43000"))
    await simulator._handle_signal_short(signal)

    assert simulator._open_trade is not None
    assert simulator._open_trade.direction == TradeDirection.SHORT
    assert simulator._open_trade.entry_price == Decimal("42000")
    assert simulator._open_trade.stop_loss == Decimal("43000")
    # TP = 42000 - 1000 * 2 = 40000
    assert simulator._open_trade.take_profit == Decimal("40000")


@pytest.mark.asyncio
async def test_sl_hit_closes_long_trade(simulator: TradeSimulator) -> None:
    """Vérifie SL détecté quand candle.low <= sl_price pour un LONG."""
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    # Bougie dont le bas atteint le SL
    candle = _make_candle(low=Decimal("40999"), high=Decimal("42500"))
    await simulator._handle_candle_closed(candle)

    assert simulator._open_trade is None
    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    assert result.exit_price == Decimal("41000")
    assert result.direction == TradeDirection.LONG


@pytest.mark.asyncio
async def test_tp_hit_closes_long_trade(simulator: TradeSimulator) -> None:
    """Vérifie TP détecté quand candle.high >= tp_price pour un LONG."""
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    # Bougie dont le haut atteint le TP (44000)
    candle = _make_candle(low=Decimal("42100"), high=Decimal("44001"))
    await simulator._handle_candle_closed(candle)

    assert simulator._open_trade is None
    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    assert result.exit_price == Decimal("44000")


@pytest.mark.asyncio
async def test_sl_hit_closes_short_trade(simulator: TradeSimulator) -> None:
    """Vérifie SL détecté quand candle.high >= sl_price pour un SHORT."""
    signal = _make_signal("SHORT", Decimal("42000"), Decimal("43000"))
    await simulator._handle_signal_short(signal)

    # Bougie dont le haut atteint le SL
    candle = _make_candle(low=Decimal("41500"), high=Decimal("43001"))
    await simulator._handle_candle_closed(candle)

    assert simulator._open_trade is None
    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    assert result.exit_price == Decimal("43000")
    assert result.direction == TradeDirection.SHORT


@pytest.mark.asyncio
async def test_fees_applied_to_pnl(simulator: TradeSimulator) -> None:
    """Calcul numérique vérifié : entry=42000, exit TP=44000, qty=0.1, rr=2.

    entry_fee = 42000 * 0.1 * 0.001 = 4.2 USDT
    exit_fee  = 44000 * 0.1 * 0.001 = 4.4 USDT
    gross_pnl = (44000 - 42000) * 0.1 = 200.0 USDT
    net_pnl   = 200.0 - 4.2 - 4.4 = 191.4 USDT
    """
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    # TP = 44000 → bougie high atteint le TP
    candle = _make_candle(low=Decimal("42100"), high=Decimal("44000"))
    await simulator._handle_candle_closed(candle)

    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    # Vérification numérique exacte
    expected_entry_fee = Decimal("42000") * Decimal("0.1") * FEE_RATE
    expected_exit_fee = Decimal("44000") * Decimal("0.1") * FEE_RATE
    expected_gross = (Decimal("44000") - Decimal("42000")) * Decimal("0.1")
    expected_net = expected_gross - expected_entry_fee - expected_exit_fee
    assert result.pnl == expected_net
    assert result.pnl == Decimal("191.4")


@pytest.mark.asyncio
async def test_no_double_trade_while_open(simulator: TradeSimulator) -> None:
    """Vérifie qu'un 2e signal est ignoré quand un trade est déjà ouvert (AC8)."""
    signal1 = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    signal2 = _make_signal("LONG", Decimal("43000"), Decimal("42000"))

    await simulator._handle_signal_long(signal1)
    first_trade = simulator._open_trade

    await simulator._handle_signal_long(signal2)
    # Le trade ouvert ne doit pas avoir changé
    assert simulator._open_trade is first_trade
    assert simulator._open_trade is not None
    assert simulator._open_trade.entry_price == Decimal("42000")


@pytest.mark.asyncio
async def test_sl_priority_over_tp_same_candle(simulator: TradeSimulator) -> None:
    """Vérifie que SL est prioritaire sur TP si les deux sont touchés dans la même bougie (AC4)."""
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    # Bougie extreme : low touche SL et high touche TP simultanément
    candle = _make_candle(low=Decimal("40900"), high=Decimal("45000"))
    await simulator._handle_candle_closed(candle)

    assert simulator._open_trade is None
    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    # SL prioritaire → exit_price = sl_price = 41000
    assert result.exit_price == Decimal("41000")
    # P&L doit être négatif (SL hit)
    assert result.pnl < Decimal("0")


@pytest.mark.asyncio
async def test_closed_trades_accessible(simulator: TradeSimulator) -> None:
    """Vérifie que simulator.closed_trades retourne la liste des trades clôturés (AC9)."""
    assert simulator.closed_trades == []

    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    candle = _make_candle(low=Decimal("40900"), high=Decimal("42200"))
    await simulator._handle_candle_closed(candle)

    trades = simulator.closed_trades
    assert len(trades) == 1
    # Retourne une copie — modification externe ne doit pas affecter l'interne
    trades.clear()
    assert len(simulator.closed_trades) == 1


@pytest.mark.asyncio
async def test_balance_updates_after_trade(simulator: TradeSimulator) -> None:
    """Vérifie que balance = capital_before + pnl_net après clôture."""
    initial_balance = Decimal("10000")

    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await simulator._handle_signal_long(signal)

    # TP hit
    candle = _make_candle(low=Decimal("42100"), high=Decimal("44000"))
    await simulator._handle_candle_closed(candle)

    result = simulator.closed_trades[0]
    expected_balance = initial_balance + result.pnl
    assert simulator._balance == expected_balance
    assert result.capital_after == expected_balance


@pytest.mark.asyncio
async def test_candle_without_open_trade_no_op(simulator: TradeSimulator) -> None:
    """Vérifie que _handle_candle_closed sans trade ouvert retourne sans erreur."""
    assert simulator._open_trade is None
    candle = _make_candle(low=Decimal("40000"), high=Decimal("45000"))
    # Ne doit pas lever d'exception
    await simulator._handle_candle_closed(candle)
    assert simulator.closed_trades == []


@pytest.mark.asyncio
async def test_tp_hit_closes_short_trade(simulator: TradeSimulator) -> None:
    """Vérifie TP détecté quand candle.low <= tp_price pour un SHORT (AC4)."""
    # SHORT: entry=42000, sl=43000 → sl_distance=1000, rr=2 → tp=40000
    signal = _make_signal("SHORT", Decimal("42000"), Decimal("43000"))
    await simulator._handle_signal_short(signal)
    assert simulator._open_trade is not None
    assert simulator._open_trade.take_profit == Decimal("40000")

    # Bougie dont le bas atteint le TP (40000) pour un SHORT
    candle = _make_candle(low=Decimal("39999"), high=Decimal("41500"))
    await simulator._handle_candle_closed(candle)

    assert simulator._open_trade is None
    assert len(simulator.closed_trades) == 1
    result = simulator.closed_trades[0]
    assert result.exit_price == Decimal("40000")
    assert result.direction == TradeDirection.SHORT
    # P&L SHORT TP : (42000 - 40000) * 0.1 - fees > 0
    assert result.pnl > Decimal("0")


@pytest.mark.asyncio
async def test_bus_subscription_signal_long_integration(
    config: StrategyConfig, mock_capital_manager: MagicMock
) -> None:
    """Vérifie que l'abonnement STRATEGY_SIGNAL_LONG via le bus ouvre un trade (MEDIUM-HIGH-3)."""
    bus = EventBus()
    sim = TradeSimulator(
        event_bus=bus,
        config=config,
        capital_manager=mock_capital_manager,
        initial_capital=Decimal("10000"),
    )
    signal = StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_LONG,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=Decimal("42000"),
        sl_price=Decimal("41000"),
    )
    await bus.emit(EventType.STRATEGY_SIGNAL_LONG, signal)

    assert sim._open_trade is not None
    assert sim._open_trade.direction == TradeDirection.LONG


@pytest.mark.asyncio
async def test_bus_subscription_candle_closed_integration(
    config: StrategyConfig, mock_capital_manager: MagicMock
) -> None:
    """Vérifie que l'abonnement CANDLE_CLOSED via le bus déclenche la détection SL/TP (MEDIUM-HIGH-3)."""
    bus = EventBus()
    sim = TradeSimulator(
        event_bus=bus,
        config=config,
        capital_manager=mock_capital_manager,
        initial_capital=Decimal("10000"),
    )
    # Ouverture directe du trade (abonnement LONG déjà testé séparément)
    signal = _make_signal("LONG", Decimal("42000"), Decimal("41000"))
    await sim._handle_signal_long(signal)
    assert sim._open_trade is not None

    # Clôture via le bus — teste l'abonnement CANDLE_CLOSED réel
    candle = _make_candle(low=Decimal("40999"), high=Decimal("42500"))
    await bus.emit(EventType.CANDLE_CLOSED, candle)

    assert sim._open_trade is None
    assert len(sim.closed_trades) == 1
