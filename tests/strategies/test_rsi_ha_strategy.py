"""Tests unitaires pour RsiHaStrategy — Story 10.2."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.core.event_bus import EventBus
from src.core.exceptions import ConfigError
from src.core.state_machine import StateMachine
from src.models.config import CapitalConfig, ConditionConfig, StrategyConfig
from src.models.events import CandleEvent, EventType
from src.models.state import StrategyStateEnum
from src.strategies.registry import StrategyRegistry
from src.strategies.rsi_ha_strategy import RsiHaStrategy


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_candle_ohlc(open_: float, high: float, low: float, close: float) -> CandleEvent:
    """Crée un CandleEvent avec OHLC explicites."""
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
    )


def make_config_rsi_ha(
    rsi_periods: list[int] | None = None,
    rsi_oversold: list[float] | None = None,
    rsi_overbought: list[float] | None = None,
    sl_lookback: int = 5,
) -> StrategyConfig:
    """Crée une StrategyConfig pour RsiHaStrategy."""
    params = {
        "rsi_periods": rsi_periods or [3, 5, 7],
        "rsi_oversold_levels": rsi_oversold or [10, 20, 30],
        "rsi_overbought_levels": rsi_overbought or [90, 80, 70],
        "sl_lookback_candles": sl_lookback,
    }
    return StrategyConfig(
        name="rsi_ha_test",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=5,
        conditions=[
            ConditionConfig(type="rsi_multi_zone", params=params),
            ConditionConfig(type="ha_confirmation", params={}),
        ],
        timeout_candles=9999,
        capital=CapitalConfig(mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=1.0),
    )


def make_strategy(
    config: StrategyConfig | None = None,
) -> tuple[RsiHaStrategy, StateMachine, EventBus]:
    """Crée une RsiHaStrategy avec StateMachine et EventBus de test."""
    bus = EventBus()
    if config is None:
        config = make_config_rsi_ha()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = RsiHaStrategy(config, sm, bus)
    return strategy, sm, bus


def make_downtrend_candles(n: int, start: float = 200.0, step: float = 10.0) -> list[CandleEvent]:
    """Génère n bougies plates en forte baisse (RSI → 0 après period+1 bougies)."""
    return [
        make_candle_ohlc(start - i * step, start - i * step, start - i * step, start - i * step)
        for i in range(n)
    ]


def make_uptrend_candles(n: int, start: float = 10.0, step: float = 10.0) -> list[CandleEvent]:
    """Génère n bougies plates en forte hausse (RSI → 100 après period+1 bougies)."""
    return [
        make_candle_ohlc(start + i * step, start + i * step, start + i * step, start + i * step)
        for i in range(n)
    ]


# ── 4.3 Enregistrement dans le registre ───────────────────────────────────────


def test_rsi_ha_is_registered() -> None:
    """RsiHaStrategy est enregistrée sous la clé 'rsi_ha' dans StrategyRegistry."""
    assert StrategyRegistry.get("rsi_ha") is RsiHaStrategy


# ── 4.4 Paramètres par défaut ─────────────────────────────────────────────────


def test_rsi_ha_default_params() -> None:
    """Instanciation sans params → valeurs par défaut correctes."""
    strategy, _, _ = make_strategy()
    assert strategy._rsi_periods == [3, 5, 7]
    assert strategy._rsi_oversold == [10, 20, 30]
    assert strategy._rsi_overbought == [90, 80, 70]
    assert strategy._sl_lookback == 5


# ── 4.5 ConfigError — mismatch longueur ───────────────────────────────────────


def test_rsi_ha_config_error_period_mismatch() -> None:
    """Longueurs inégales entre rsi_periods et niveaux → ConfigError."""
    with pytest.raises(ConfigError):
        make_strategy(make_config_rsi_ha(rsi_periods=[3, 5], rsi_oversold=[10, 20, 30]))


# ── 4.6 ConfigError — oversold >= overbought ──────────────────────────────────


def test_rsi_ha_config_error_invalid_levels() -> None:
    """oversold >= overbought pour un index → ConfigError."""
    with pytest.raises(ConfigError):
        make_strategy(
            make_config_rsi_ha(rsi_oversold=[30, 20, 10], rsi_overbought=[25, 80, 70])
        )


# ── 4.7 Signal LONG ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_long_signal_triggered() -> None:
    """3 RSI en oversold + bougie HA bullish → STRATEGY_SIGNAL_LONG."""
    strategy, sm, bus = make_strategy()

    received: list[object] = []

    async def capture(event: object) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_LONG, capture)

    # Phase 1 : 20 bougies en forte baisse → RSI(3,5,7) = 0 ≤ [10,20,30]
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    # La phase 1 est déclenchée à la 8ème bougie (RSI(7) a besoin de 8)
    assert sm.state == StrategyStateEnum.WATCHING
    assert strategy._signal_direction == "long"

    # Phase 2 : bougie HA bullish
    # Après downtrend [200..10] : ha_open ≈ 20, ha_close = 27.5 → bullish
    recovery = make_candle_ohlc(10, 50, 10, 40)
    await strategy.evaluate_conditions(recovery)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    assert len(received) == 1


# ── 4.8 Signal SHORT ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_short_signal_triggered() -> None:
    """3 RSI en overbought + bougie HA bearish → STRATEGY_SIGNAL_SHORT."""
    strategy, sm, bus = make_strategy()

    received: list[object] = []

    async def capture(event: object) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_SHORT, capture)

    # Phase 1 : 20 bougies en forte hausse → RSI(3,5,7) = 100 ≥ [90,80,70]
    for candle in make_uptrend_candles(20):
        await strategy.evaluate_conditions(candle)

    assert sm.state == StrategyStateEnum.WATCHING
    assert strategy._signal_direction == "short"

    # Phase 2 : bougie HA bearish
    # Après uptren [10..200] : ha_open ≈ 190, ha_close = 181.25 → bearish
    reversal = make_candle_ohlc(200, 200, 160, 165)
    await strategy.evaluate_conditions(reversal)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    assert len(received) == 1


# ── 4.9a Pas de signal si données insuffisantes ───────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_no_signal_insufficient_data() -> None:
    """Garde données insuffisantes : 7 bougies < max_period+1=8 → aucun signal.

    _check_rsi_zone() retourne None immédiatement car RSI(7) n'a pas encore
    assez de données. Ce test couvre la garde d'initialisation.
    """
    strategy, sm, _ = make_strategy()

    for candle in make_downtrend_candles(7):
        await strategy.evaluate_conditions(candle)

    assert sm.state == StrategyStateEnum.IDLE
    assert strategy._signal_direction is None


# ── 4.9b AC5 réel : données suffisantes mais RSI(7) hors zone ─────────────────


def test_rsi_ha_no_signal_partial_rsi_ac5() -> None:
    """AC5 réel : données suffisantes, mais RSI(7) hors zone oversold → _check_rsi_zone retourne None.

    Simule le cas où RSI(3)≤10 et RSI(5)≤20 sont en zone mais RSI(7)=40 > 30.
    Valide que la condition all() sur les 3 RSI est stricte — un seul RSI hors zone
    suffit à bloquer le signal.
    """
    strategy, sm, _ = make_strategy()

    # Historique suffisant pour que max_period+1=8 bougies soient disponibles
    strategy._candle_history = make_downtrend_candles(8)  # type: ignore[attr-defined]

    # Patcher RSI(7) (index 2) pour retourner 40 > seuil oversold 30
    mock_rsi7 = MagicMock()
    mock_rsi7.compute.return_value = [None] * 7 + [Decimal("40")]
    strategy._rsi_indicators[2] = mock_rsi7  # type: ignore[attr-defined]

    result = strategy._check_rsi_zone()  # type: ignore[attr-defined]

    # RSI(7)=40 > 30 → aucune zone oversold → None
    assert result is None
    assert sm.state == StrategyStateEnum.IDLE


# ── 4.10 Attente indéfinie en phase 2 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_waiting_indefinitely() -> None:
    """Phase 1 satisfaite + 10 bougies HA non confirmatoires → reste WATCHING indéfiniment."""
    strategy, sm, _ = make_strategy()

    # Phase 1 : déclencher RSI oversold
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    assert sm.state == StrategyStateEnum.WATCHING

    # 10 bougies non confirmatoires (downtrend continue, HA bearish)
    for _ in range(10):
        non_confirming = make_candle_ohlc(9, 9, 8, 9)
        await strategy.evaluate_conditions(non_confirming)

    # Doit toujours être en WATCHING — pas de timeout
    assert sm.state == StrategyStateEnum.WATCHING


# ── 4.11 SL LONG = min(low) des 5 dernières bougies ─────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_sl_long_is_min_low() -> None:
    """Signal LONG → get_sl_price() == min(low) des 5 dernières bougies."""
    strategy, sm, _ = make_strategy()

    # 20 bougies downtrend plates [200, 190, ..., 10] : low = prix de chaque bougie
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    # Recovery HA bullish : low = 10
    recovery = make_candle_ohlc(10, 50, 10, 40)
    await strategy.evaluate_conditions(recovery)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    # Candles 16-20 (0-indexed) → lows : 40, 30, 20, 10, 10
    # min = 10
    assert strategy.get_sl_price() == Decimal("10")


# ── 4.12 SL SHORT = max(high) des 5 dernières bougies ────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_sl_short_is_max_high() -> None:
    """Signal SHORT → get_sl_price() == max(high) des 5 dernières bougies."""
    strategy, sm, _ = make_strategy()

    # 20 bougies uptrend plates [10, 20, ..., 200] : high = prix de chaque bougie
    for candle in make_uptrend_candles(20):
        await strategy.evaluate_conditions(candle)

    # Reversal HA bearish : high = 200
    reversal = make_candle_ohlc(200, 200, 160, 165)
    await strategy.evaluate_conditions(reversal)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    # Candles 16-20 (0-indexed) → highs : 170, 180, 190, 200, 200
    # max = 200
    assert strategy.get_sl_price() == Decimal("200")


# ── 4.13 SL avec moins de bougies que lookback ───────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_sl_fewer_candles_than_lookback() -> None:
    """sl_lookback > nb bougies disponibles → list[-n:] retourne tout l'historique."""
    config = make_config_rsi_ha(sl_lookback=50)
    strategy, sm, _ = make_strategy(config)

    # 20 bougies downtrend + 1 recovery = 21 candles total (< 50 sl_lookback)
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    recovery = make_candle_ohlc(10, 50, 10, 40)
    await strategy.evaluate_conditions(recovery)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    # sl_lookback=50 > 21 candles → Python [-50:] sur 21 éléments = tout l'historique
    # min(lows) de toutes les 21 bougies = 10
    sl = strategy.get_sl_price()
    assert sl is not None
    assert sl == Decimal("10")


# ── 4.14 get_signal() retourne la direction ──────────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_get_signal_returns_direction() -> None:
    """get_signal() retourne la direction correcte à chaque phase."""
    strategy, _, _ = make_strategy()

    # Avant tout signal → retourne "long" par défaut (contrat BaseStrategy)
    assert strategy.get_signal() == "long"

    # Après phase 1 LONG → retourne "long"
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    assert strategy.get_signal() == "long"

    # Stratégie indépendante → phase 1 SHORT → retourne "short"
    strategy2, _, _ = make_strategy()
    for candle in make_uptrend_candles(20):
        await strategy2.evaluate_conditions(candle)

    assert strategy2.get_signal() == "short"


# ── 4.16 Paramètres RSI personnalisés (période unique) ───────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_custom_params_single_period() -> None:
    """Config avec une seule période RSI (rsi_periods=[14]) et seuils custom.

    Vérifie que la stratégie fonctionne avec n=1 RSI au lieu de 3,
    et que le sl_lookback=3 est respecté dans le calcul du SL.
    """
    config = make_config_rsi_ha(
        rsi_periods=[14],
        rsi_oversold=[30],
        rsi_overbought=[70],
        sl_lookback=3,
    )
    strategy, sm, bus = make_strategy(config)

    # Vérifier les attributs internes
    assert strategy._rsi_periods == [14]
    assert strategy._rsi_oversold == [30]
    assert strategy._rsi_overbought == [70]
    assert strategy._sl_lookback == 3
    assert strategy._max_rsi_period == 14
    assert strategy._history_max_size == max(14 * 10, 3)  # = 140

    received: list[object] = []

    async def capture(event: object) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_LONG, capture)

    # 20 bougies en forte baisse → RSI(14) → 0 ≤ 30 → Phase 1
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    assert sm.state == StrategyStateEnum.WATCHING
    assert strategy._signal_direction == "long"

    # Bougie HA bullish pour Phase 2
    recovery = make_candle_ohlc(10, 50, 10, 40)
    await strategy.evaluate_conditions(recovery)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    assert len(received) == 1

    # SL = min(low) des 3 dernières bougies (sl_lookback=3)
    sl = strategy.get_sl_price()
    assert sl is not None
    assert sl == Decimal("10")


# ── 4.17 Bornage de l'historique (_history_max_size) ─────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_history_bounded() -> None:
    """L'historique _candle_history est borné à _history_max_size pour éviter O(n²).

    Avec rsi_periods=[3,5,7] : _history_max_size = max(7*10, 5) = 70.
    Après 80 bougies, l'historique doit contenir exactement 70 bougies.
    """
    strategy, _, _ = make_strategy()

    max_size = strategy._history_max_size  # = 70
    assert max_size == 70  # max(7*10, 5) pour les paramètres par défaut

    for candle in make_downtrend_candles(max_size + 10):
        await strategy.evaluate_conditions(candle)

    assert len(strategy._candle_history) == max_size


# ── 4.18 Réinitialisation d'état inter-cycles ─────────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_state_reset_on_new_cycle() -> None:
    """Phase 1 réinitialise _signal_direction et _computed_sl_price en début de cycle.

    Quand la stratégie est en conditions_met=0 (IDLE ou après reset),
    les états internes doivent être remis à None avant toute évaluation.
    """
    strategy, sm, _ = make_strategy()

    # Pré-condition : injecter un état "sale" simulant une réutilisation
    strategy._signal_direction = "short"  # type: ignore[attr-defined]
    strategy._computed_sl_price = Decimal("999")  # type: ignore[attr-defined]

    # Envoyer une bougie en Phase 1 (conditions_met == 0) — reset doit se faire
    # AVANT l'évaluation de la zone RSI, même si la zone n'est pas atteinte
    candle = make_candle_ohlc(100, 101, 99, 100)  # bougie neutre, RSI insuffisant
    await strategy.evaluate_conditions(candle)

    # Les états doivent être réinitialisés puisque conditions_met == 0
    assert strategy._signal_direction is None
    assert strategy._computed_sl_price is None
    assert sm.state == StrategyStateEnum.IDLE


# ── 4.15 HA mauvaise direction → reste WATCHING ──────────────────────────────


@pytest.mark.asyncio
async def test_rsi_ha_ha_wrong_direction_no_signal() -> None:
    """Phase 1 LONG satisfaite, bougie HA bearish → pas de signal (reste WATCHING)."""
    strategy, sm, _ = make_strategy()

    # Phase 1 : déclencher RSI oversold (LONG)
    for candle in make_downtrend_candles(20):
        await strategy.evaluate_conditions(candle)

    assert sm.state == StrategyStateEnum.WATCHING
    assert strategy._signal_direction == "long"

    # Bougie HA bearish (downtrend continue) → ne confirme PAS le LONG
    # Après downtrend, ha_open ≈ 20 >> ha_close ≈ 8.75 → bearish
    bearish_candle = make_candle_ohlc(9, 9, 8, 9)
    await strategy.evaluate_conditions(bearish_candle)

    # Doit rester en WATCHING (pas de timeout dans cette stratégie)
    assert sm.state == StrategyStateEnum.WATCHING
    assert strategy.get_sl_price() is None
