"""Tests d'intégration TradeSimulator + MartingaleCapitalManager — Story 7.3.

Couvre AC #1 (même PositionSizer), AC #2 (plafonnement en backtest), AC #4 (parité live/backtest).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, call

import pytest

from src.backtest.trade_simulator import TradeSimulator
from src.capital.martingale import MartingaleCapitalManager
from src.core.event_bus import EventBus
from src.models.config import CapitalConfig, StrategyConfig
from src.models.events import CandleEvent, EventType, StrategyEvent
from src.models.exchange import MarketRules


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_martingale_config(
    factor: float = 2.0,
    max_steps: int | None = 3,
    risk_percent: float = 1.0,
) -> CapitalConfig:
    return CapitalConfig(
        mode="martingale",
        risk_percent=risk_percent,
        risk_reward_ratio=2.0,
        factor=factor,
        max_steps=max_steps,
    )


def make_market_rules() -> MarketRules:
    return MarketRules(
        step_size=Decimal("0.001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("5"),
        max_leverage=125,
    )


def make_martingale_simulator(
    factor: float = 2.0,
    max_steps: int | None = 3,
    initial_capital: Decimal = Decimal("10000"),
) -> tuple[TradeSimulator, MartingaleCapitalManager]:
    """Crée un TradeSimulator avec un MartingaleCapitalManager réel."""
    bus = EventBus()
    config = StrategyConfig(
        name="test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[],
        timeout_candles=10,
        capital=make_martingale_config(factor=factor, max_steps=max_steps),
    )
    capital_manager = MartingaleCapitalManager(
        make_martingale_config(factor=factor, max_steps=max_steps),
        make_market_rules(),
    )
    simulator = TradeSimulator(
        event_bus=bus,
        config=config,
        capital_manager=capital_manager,
        initial_capital=initial_capital,
    )
    return simulator, capital_manager


def _make_long_signal(
    signal_price: Decimal = Decimal("42000"),
    sl_price: Decimal = Decimal("41000"),
) -> StrategyEvent:
    return StrategyEvent(
        event_type=EventType.STRATEGY_SIGNAL_LONG,
        strategy_name="test",
        pair="BTC/USDT",
        signal_price=signal_price,
        sl_price=sl_price,
    )


def _make_sl_candle() -> CandleEvent:
    """Bougie qui touche le SL (low <= 41000) → perte."""
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal("42000"),
        high=Decimal("42500"),
        low=Decimal("40000"),
        close=Decimal("41500"),
        volume=Decimal("10"),
    )


def _make_tp_candle() -> CandleEvent:
    """Bougie qui touche le TP (high >= 44000) → gain."""
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal("42000"),
        high=Decimal("45000"),
        low=Decimal("42100"),
        close=Decimal("44500"),
        volume=Decimal("10"),
    )


# ── Tests AC1 : MartingaleCapitalManager utilisé en backtest ──────────────────


@pytest.mark.asyncio
async def test_ac1_martingale_after_loss_increases_risk() -> None:
    """AC1 : après 1 perte, le trade suivant utilise risk × factor (qty doublée).

    Scénario : 2 trades consécutifs en martingale (factor=2.0).
    Trade 1 : base risk=1.0%, SL hit.
    Trade 2 : effective risk=2.0%, même SL distance → qty × 2.
    """
    simulator, capital_manager = make_martingale_simulator(factor=2.0, max_steps=3)

    # Trade 1 (base risk=1%) — ouverture
    signal = _make_long_signal()
    await simulator._handle_signal_long(signal)
    assert simulator._open_trade is not None
    qty_trade1 = simulator._open_trade.quantity
    risk_trade1 = simulator._open_trade.risk_percent
    assert risk_trade1 == pytest.approx(1.0)

    # Trade 1 — clôture par SL (perte)
    sl_candle = _make_sl_candle()
    await simulator._handle_candle_closed(sl_candle)
    assert len(simulator.closed_trades) == 1
    assert simulator.closed_trades[0].risk_percent == pytest.approx(1.0)

    # Trade 2 (effective risk=2.0% après 1 perte) — ouverture
    signal2 = _make_long_signal()
    await simulator._handle_signal_long(signal2)
    assert simulator._open_trade is not None
    qty_trade2 = simulator._open_trade.quantity
    risk_trade2 = simulator._open_trade.risk_percent
    assert risk_trade2 == pytest.approx(2.0)

    # Quantité doublée (même SL distance, même balance approximativement)
    assert qty_trade2 > qty_trade1


@pytest.mark.asyncio
async def test_ac1_martingale_after_win_resets_risk() -> None:
    """AC1 : après 1 perte puis 1 gain, le 3ème trade revient au risk de base."""
    simulator, _ = make_martingale_simulator(factor=2.0, max_steps=3)

    # Trade 1 — perte
    await simulator._handle_signal_long(_make_long_signal())
    risk1 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    await simulator._handle_candle_closed(_make_sl_candle())

    # Trade 2 — gain (effective risk = 2%)
    await simulator._handle_signal_long(_make_long_signal())
    risk2 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk2 == pytest.approx(2.0)
    await simulator._handle_candle_closed(_make_tp_candle())

    # Trade 3 — retour au base risk (1%)
    await simulator._handle_signal_long(_make_long_signal())
    risk3 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk3 == pytest.approx(1.0)
    assert risk1 == risk3


# ── Tests AC2 : Plafonnement max_steps en backtest ────────────────────────────


@pytest.mark.asyncio
async def test_ac2_max_steps_capping_in_backtest() -> None:
    """AC2 : après max_steps=3 pertes consécutives, le risk est plafonné.

    Séquence : L, L, L (3 pertes → consecutive=3=max_steps → plafonné)
    Trade 4 (4ème perte) : risk identique au trade 3.
    """
    simulator, _ = make_martingale_simulator(factor=2.0, max_steps=3)

    # 3 pertes consécutives
    risk_percents = []
    for _ in range(3):
        await simulator._handle_signal_long(_make_long_signal())
        risk_percents.append(simulator._open_trade.risk_percent)  # type: ignore[union-attr]
        await simulator._handle_candle_closed(_make_sl_candle())

    # Vérification progression : 1.0 → 2.0 → 4.0
    assert risk_percents[0] == pytest.approx(1.0)  # base
    assert risk_percents[1] == pytest.approx(2.0)  # × factor^1
    assert risk_percents[2] == pytest.approx(4.0)  # × factor^2

    # 4ème trade : plafonné à factor^3 = 8.0 (max_steps=3)
    await simulator._handle_signal_long(_make_long_signal())
    risk_trade4 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk_trade4 == pytest.approx(8.0)  # base × 2^3 = 8.0

    # 5ème perte : risk identique (toujours 8.0, pas de dépassement)
    await simulator._handle_candle_closed(_make_sl_candle())
    await simulator._handle_signal_long(_make_long_signal())
    risk_trade5 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk_trade5 == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_ac2_risk_percent_stored_in_trade_result() -> None:
    """AC2/AC3 : le risk_percent est correctement stocké dans chaque TradeResult."""
    simulator, _ = make_martingale_simulator(factor=2.0, max_steps=3)

    # Trade 1 — perte
    await simulator._handle_signal_long(_make_long_signal())
    await simulator._handle_candle_closed(_make_sl_candle())

    # Trade 2 — perte
    await simulator._handle_signal_long(_make_long_signal())
    await simulator._handle_candle_closed(_make_sl_candle())

    trades = simulator.closed_trades
    assert len(trades) == 2
    assert trades[0].risk_percent == pytest.approx(1.0)
    assert trades[1].risk_percent == pytest.approx(2.0)


# ── Tests AC4 : Parité live/backtest ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac4_parity_same_sequence_same_risk_evolution() -> None:
    """AC4 : la même séquence W/L produit la même évolution de risk_percent.

    Simule deux 'runs' avec la même séquence L, W, L, L.
    L'évolution du risk_percent doit être identique.
    """

    def run_sequence(sequence: list[bool]) -> list[float | None]:
        """Simule une séquence W/L et retourne les risk_percents utilisés."""
        manager = MartingaleCapitalManager(
            make_martingale_config(factor=2.0, max_steps=3),
            make_market_rules(),
        )
        risk_percents = []
        for won in sequence:
            risk_percents.append(manager.get_current_risk_percent())
            manager.record_trade_result(won)
        return risk_percents

    sequence = [False, True, False, False]  # L, W, L, L
    run1 = run_sequence(sequence)
    run2 = run_sequence(sequence)

    assert run1 == run2
    # Vérification des valeurs attendues : 1.0, 2.0, 1.0, 2.0
    assert run1[0] == pytest.approx(1.0)  # avant tout trade
    assert run1[1] == pytest.approx(2.0)  # après 1 perte
    assert run1[2] == pytest.approx(1.0)  # après reset (win)
    assert run1[3] == pytest.approx(2.0)  # après 1 perte


# ── Test AC1/AC4 : mode martingale_inverse ────────────────────────────────────


@pytest.mark.asyncio
async def test_ac1_martingale_inverse_after_win_increases_risk() -> None:
    """martingale_inverse : trigger sur GAIN (multiply), reset sur PERTE.

    Scénario : 3 trades en martingale_inverse (factor=2.0).
    Trade 1 : base risk=1.0%, TP hit (gain) → risk double pour trade 2.
    Trade 2 : effective risk=2.0%, SL hit (perte) → risk réinitialisé pour trade 3.
    Trade 3 : retour au base risk=1.0%.
    """
    bus = EventBus()
    inverse_config = CapitalConfig(
        mode="martingale_inverse",
        risk_percent=1.0,
        risk_reward_ratio=2.0,
        factor=2.0,
        max_steps=3,
    )
    strategy_config = StrategyConfig(
        name="test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[],
        timeout_candles=10,
        capital=inverse_config,
    )
    capital_manager = MartingaleCapitalManager(inverse_config, make_market_rules())
    simulator = TradeSimulator(
        event_bus=bus,
        config=strategy_config,
        capital_manager=capital_manager,
        initial_capital=Decimal("10000"),
    )

    # Trade 1 (base risk=1%) — clôture par TP (GAIN → trigger en mode inverse)
    await simulator._handle_signal_long(_make_long_signal())
    risk1 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk1 == pytest.approx(1.0)
    await simulator._handle_candle_closed(_make_tp_candle())

    # Trade 2 : effective risk=2.0% (multiplié après 1 gain)
    await simulator._handle_signal_long(_make_long_signal())
    risk2 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk2 == pytest.approx(2.0)

    # Trade 2 — clôture par SL (PERTE → reset en mode inverse)
    await simulator._handle_candle_closed(_make_sl_candle())

    # Trade 3 : retour au base risk=1.0% (reset après perte)
    await simulator._handle_signal_long(_make_long_signal())
    risk3 = simulator._open_trade.risk_percent  # type: ignore[union-attr]
    assert risk3 == pytest.approx(1.0)
    assert risk1 == risk3


# ── Test : record_trade_result appelé après chaque clôture ────────────────────


@pytest.mark.asyncio
async def test_record_trade_result_called_after_close() -> None:
    """Vérifie que record_trade_result() est appelé après chaque trade clôturé."""
    bus = EventBus()
    config = StrategyConfig(
        name="test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[],
        timeout_candles=10,
        capital=make_martingale_config(),
    )
    mock_manager = MagicMock()
    mock_manager.calculate_position_size.return_value = Decimal("0.1")
    mock_manager.get_current_risk_percent.return_value = 1.0

    simulator = TradeSimulator(
        event_bus=bus,
        config=config,
        capital_manager=mock_manager,
        initial_capital=Decimal("10000"),
    )

    # Trade SL hit → won=False
    await simulator._handle_signal_long(_make_long_signal())
    await simulator._handle_candle_closed(_make_sl_candle())

    mock_manager.record_trade_result.assert_called_once_with(False)

    # Trade TP hit → won=True
    await simulator._handle_signal_long(_make_long_signal())
    await simulator._handle_candle_closed(_make_tp_candle())

    assert mock_manager.record_trade_result.call_count == 2
    assert mock_manager.record_trade_result.call_args_list == [call(False), call(True)]
