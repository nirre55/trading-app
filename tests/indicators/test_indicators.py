"""Tests unitaires pour BaseIndicator, RSIIndicator et IndicatorRegistry."""

from decimal import Decimal

import pytest

from src.core.exceptions import ConfigError
from src.indicators.base import BaseIndicator
from src.indicators.registry import IndicatorRegistry
from src.indicators.rsi import RSIIndicator
from src.models.events import CandleEvent, EventType


# ── Fixtures helpers ─────────────────────────────────────────────────────────


def make_candle(close: float) -> CandleEvent:
    """Crée un CandleEvent de test."""
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal(str(close)),
        high=Decimal(str(close + 100)),
        low=Decimal(str(close - 100)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
    )


def make_candles_rising(
    n: int, start: float = 100.0, step: float = 1.0
) -> list[CandleEvent]:
    """Crée n bougies en hausse constante (RSI → 100)."""
    return [make_candle(start + i * step) for i in range(n)]


def make_candles_falling(
    n: int, start: float = 200.0, step: float = 1.0
) -> list[CandleEvent]:
    """Crée n bougies en baisse constante (RSI → 0)."""
    return [make_candle(start - i * step) for i in range(n)]


def make_candles_alternating(n: int, start: float = 100.0) -> list[CandleEvent]:
    """Crée n bougies alternant hausse/baisse égales (RSI ≈ 50)."""
    prices = []
    for i in range(n):
        prices.append(start + (1.0 if i % 2 == 0 else -1.0))
        start = prices[-1]
    return [make_candle(p) for p in prices]


# ── Tests interface abstraite ─────────────────────────────────────────────────


def test_base_indicator_is_abstract() -> None:
    """BaseIndicator directement instanciée → TypeError."""
    with pytest.raises(TypeError):
        BaseIndicator()  # type: ignore[abstract]


def test_rsi_indicator_implements_interface() -> None:
    """RSIIndicator() peut être instanciée."""
    rsi = RSIIndicator()
    assert isinstance(rsi, BaseIndicator)


# ── Tests RSI — données insuffisantes ────────────────────────────────────────


def test_rsi_insufficient_data_returns_all_none() -> None:
    """5 candles avec period=14 → liste de 5 None."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_rising(5)
    result = rsi.compute(candles)
    assert len(result) == 5
    assert all(v is None for v in result)


def test_rsi_exactly_period_candles_returns_all_none() -> None:
    """14 candles avec period=14 → 14 None (besoin de period+1)."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_rising(14)
    result = rsi.compute(candles)
    assert len(result) == 14
    assert all(v is None for v in result)


# ── Tests RSI — valeurs correctes ────────────────────────────────────────────


def test_rsi_all_rising_equals_100() -> None:
    """20 bougies en hausse constante → dernier RSI = 100."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_rising(20)
    result = rsi.compute(candles)
    last_value = result[-1]
    assert last_value is not None
    assert last_value == Decimal(100)


def test_rsi_all_falling_equals_0() -> None:
    """20 bougies en baisse constante → dernier RSI = 0."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_falling(20)
    result = rsi.compute(candles)
    last_value = result[-1]
    assert last_value is not None
    assert last_value == Decimal(0)


def test_rsi_returns_list_same_length() -> None:
    """len(result) == len(candles) toujours."""
    rsi = RSIIndicator(period=14)
    for n in [5, 14, 15, 20, 50]:
        candles = make_candles_rising(n)
        result = rsi.compute(candles)
        assert len(result) == n, f"Longueur incorrecte pour n={n}"


def test_rsi_first_period_values_are_none() -> None:
    """result[:14] tous None avec period=14 par défaut."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_rising(20)
    result = rsi.compute(candles)
    assert all(v is None for v in result[:14])
    assert result[14] is not None


def test_rsi_value_between_0_and_100() -> None:
    """Valeur RSI non-None toujours dans [0, 100]."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_alternating(30)
    result = rsi.compute(candles)
    for v in result:
        if v is not None:
            assert Decimal(0) <= v <= Decimal(100), f"RSI hors bornes : {v}"


# ── Tests RSI — période personnalisée ────────────────────────────────────────


def test_rsi_custom_period() -> None:
    """RSIIndicator(period=5) → 5 premiers None, 6ème non-None."""
    rsi = RSIIndicator(period=5)
    candles = make_candles_rising(10)
    result = rsi.compute(candles)
    assert all(v is None for v in result[:5])
    assert result[5] is not None


def test_rsi_period_property() -> None:
    """RSIIndicator(period=7).period == 7."""
    rsi = RSIIndicator(period=7)
    assert rsi.period == 7


# ── Tests du registre ─────────────────────────────────────────────────────────


def test_registry_register_and_get() -> None:
    """register('test_ind', RSIIndicator) → get('test_ind') retourne RSIIndicator."""
    IndicatorRegistry.register("test_ind_register", RSIIndicator)
    try:
        result = IndicatorRegistry.get("test_ind_register")
        assert result is RSIIndicator
    finally:
        IndicatorRegistry._registry.pop("test_ind_register", None)


def test_registry_get_unknown_raises_config_error() -> None:
    """get('inexistant') → lève ConfigError avec match='introuvable'."""
    with pytest.raises(ConfigError, match="introuvable"):
        IndicatorRegistry.get("inexistant_xyz_abc")


def test_registry_list_available_contains_rsi() -> None:
    """Après import rsi.py, 'rsi' dans list_available()."""
    available = IndicatorRegistry.list_available()
    assert "rsi" in available


def test_registry_decorator_registers_indicator() -> None:
    """@IndicatorRegistry.indicator('custom_test') → disponible via get() (FR5)."""

    @IndicatorRegistry.indicator("custom_test_decorator")
    class CustomTestIndicator(BaseIndicator):
        def compute(self, candles: list[CandleEvent]) -> list[Decimal | None]:
            return [None] * len(candles)

    try:
        result = IndicatorRegistry.get("custom_test_decorator")
        assert result is CustomTestIndicator
    finally:
        IndicatorRegistry._registry.pop("custom_test_decorator", None)


# ── Test FR4 ──────────────────────────────────────────────────────────────────


def test_fr4_indicator_loaded_by_name_from_registry() -> None:
    """IndicatorRegistry.get('rsi') retourne RSIIndicator, instanciable et fonctionnelle."""
    indicator_class = IndicatorRegistry.get("rsi")
    assert indicator_class is RSIIndicator

    # Instanciable
    indicator = indicator_class()
    assert isinstance(indicator, RSIIndicator)

    # compute() retourne liste de bonne longueur
    candles = make_candles_rising(20)
    result = indicator.compute(candles)
    assert len(result) == len(candles)


# ── Tests corrections code review ────────────────────────────────────────────


def test_rsi_equal_gains_losses_equals_50() -> None:
    """Bougies alternant hausses/baisses égales → RSI = 50 au premier point calculé (AC2 + Task 4.5)."""
    rsi = RSIIndicator(period=14)
    candles = make_candles_alternating(30)
    result = rsi.compute(candles)
    # Mathématiquement : avg_gain = avg_loss = 7/14 = 0.5 → RSI = 100 - 100/(1+1) = 50 exact
    first_rsi = result[14]
    assert first_rsi is not None
    assert first_rsi == Decimal(50), f"RSI attendu = 50, obtenu {first_rsi}"


def test_rsi_flat_market_returns_50() -> None:
    """Marché plat (tous mêmes prix) → RSI = 50 (neutre), pas 100 (H1 fix)."""
    rsi = RSIIndicator(period=14)
    candles = [make_candle(100.0)] * 20
    result = rsi.compute(candles)
    non_none = [v for v in result if v is not None]
    assert len(non_none) > 0
    for v in non_none:
        assert v == Decimal(50), f"RSI marché plat doit être 50 (neutre), obtenu {v}"


def test_base_indicator_invalid_period_raises() -> None:
    """BaseIndicator avec period <= 0 → ValueError (M2 fix)."""
    with pytest.raises(ValueError, match="période"):
        RSIIndicator(period=0)
    with pytest.raises(ValueError, match="période"):
        RSIIndicator(period=-5)
