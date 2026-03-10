"""Tests unitaires pour HeikinAshiIndicator."""

from decimal import Decimal

import pytest

from src.indicators.heikin_ashi import HeikinAshiIndicator
from src.indicators.registry import IndicatorRegistry
from src.models.events import CandleEvent, EventType


def make_candle_ohlc(open_: float, high: float, low: float, close: float) -> CandleEvent:
    """Crée un CandleEvent OHLC pour les tests."""
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


def make_candle(close: float) -> CandleEvent:
    """Crée un CandleEvent simple pour les tests (high=close+1, low=close-1).

    Note : utiliser des valeurs close >= 1 pour éviter un low négatif.
    """
    return make_candle_ohlc(close, close + 1, max(close - 1, 0.01), close)


# Fixtures de bougies connues pour le test manuel
CANDLES_5 = [
    make_candle_ohlc(10, 12, 9, 11),   # i=0 → None
    make_candle_ohlc(11, 13, 10, 12),  # i=1 → Decimal(1)
    make_candle_ohlc(12, 14, 11, 13),  # i=2 → Decimal(1)
    make_candle_ohlc(13, 13, 8, 8),    # i=3 → Decimal(0)
    make_candle_ohlc(8, 9, 7, 8),      # i=4 → Decimal(0)
]

# Tableau de calcul HA (10 bougies) — valeurs vérifiées manuellement
# Format: i | OHLC | HA_Close | HA_Open | direction
#  i=0 : (10,12,9,11)  → HA_Close=10.5,  HA_Open=(10+11)/2=10.5          → None
#  i=1 : (11,13,10,12) → HA_Close=11.5,  HA_Open=(10.5+10.5)/2=10.5      → Decimal(1) [11.5>10.5]
#  i=2 : (12,14,11,13) → HA_Close=12.5,  HA_Open=(10.5+11.5)/2=11.0      → Decimal(1) [12.5>11.0]
#  i=3 : (13,13,8,8)   → HA_Close=10.5,  HA_Open=(11.0+12.5)/2=11.75     → Decimal(0) [10.5<11.75]
#  i=4 : (8,9,7,8)     → HA_Close=8.0,   HA_Open=(11.75+10.5)/2=11.125   → Decimal(0) [8.0<11.125]
#  i=5 : (8,9,7,8)     → HA_Close=8.0,   HA_Open=(11.125+8.0)/2=9.5625   → Decimal(0) [8.0<9.5625]
#  i=6 : (8,20,8,18)   → HA_Close=13.5,  HA_Open=(9.5625+8.0)/2=8.78125  → Decimal(1) [13.5>8.78125]
#  i=7 : (18,22,17,21) → HA_Close=19.5,  HA_Open=(8.78125+13.5)/2=11.140625  → Decimal(1) [19.5>11.140625]
#  i=8 : (21,22,10,10) → HA_Close=15.75, HA_Open=(11.140625+19.5)/2=15.3203125  → Decimal(1) [15.75>15.3203125]
#  i=9 : (10,11,5,6)   → HA_Close=8.0,   HA_Open=(15.3203125+15.75)/2=15.53515625  → Decimal(0) [8.0<15.535]
CANDLES_10 = [
    make_candle_ohlc(10, 12, 9, 11),    # i=0 → None
    make_candle_ohlc(11, 13, 10, 12),   # i=1 → Decimal(1)
    make_candle_ohlc(12, 14, 11, 13),   # i=2 → Decimal(1)
    make_candle_ohlc(13, 13, 8, 8),     # i=3 → Decimal(0)
    make_candle_ohlc(8, 9, 7, 8),       # i=4 → Decimal(0)
    make_candle_ohlc(8, 9, 7, 8),       # i=5 → Decimal(0)
    make_candle_ohlc(8, 20, 8, 18),     # i=6 → Decimal(1)
    make_candle_ohlc(18, 22, 17, 21),   # i=7 → Decimal(1)
    make_candle_ohlc(21, 22, 10, 10),   # i=8 → Decimal(1)
    make_candle_ohlc(10, 11, 5, 6),     # i=9 → Decimal(0)
]


# 3.1 — Enregistrement dans le registre
def test_heikin_ashi_is_registered() -> None:
    """IndicatorRegistry.get("heikin_ashi") retourne HeikinAshiIndicator."""
    assert IndicatorRegistry.get("heikin_ashi") is HeikinAshiIndicator


# 3.2 — Liste vide
def test_heikin_ashi_empty_candles_returns_empty_list() -> None:
    """compute([]) → []."""
    indicator = HeikinAshiIndicator()
    result = indicator.compute([])
    assert result == []


# 3.3 — Une seule bougie
def test_heikin_ashi_single_candle_returns_none() -> None:
    """compute([c0]) → [None]."""
    indicator = HeikinAshiIndicator()
    candle = make_candle(10.0)
    result = indicator.compute([candle])
    assert result == [None]


# 3.4 — Longueur du résultat == longueur de l'entrée
def test_heikin_ashi_len_result_equals_len_candles() -> None:
    """len(result) == len(candles) pour 1, 2, 5 et 10 bougies."""
    indicator = HeikinAshiIndicator()
    for n in [1, 2, 5, 10]:
        candles = [make_candle(i + 10) for i in range(n)]
        result = indicator.compute(candles)
        assert len(result) == n, f"Attendu {n} valeurs, obtenu {len(result)}"


# 3.5 — Première valeur toujours None
def test_heikin_ashi_first_value_is_none() -> None:
    """result[0] est None pour toute entrée ≥ 1 bougie."""
    indicator = HeikinAshiIndicator()
    for n in [1, 2, 5]:
        candles = [make_candle(float(i + 10)) for i in range(n)]
        result = indicator.compute(candles)
        assert result[0] is None, f"result[0] devrait être None pour {n} bougies"


# 3.6 — Vérification manuelle sur 5 bougies connues
def test_heikin_ashi_manual_5_candles() -> None:
    """Vérification manuelle complète sur 5 bougies avec valeurs calculées à la main.

    Tableau de calcul :
    i=0 : HA_Close=(10+12+9+11)/4=10.5, HA_Open=(10+11)/2=10.5          → None
    i=1 : HA_Close=(11+13+10+12)/4=11.5, HA_Open=(10.5+10.5)/2=10.5    → Decimal(1) (11.5>10.5)
    i=2 : HA_Close=(12+14+11+13)/4=12.5, HA_Open=(10.5+11.5)/2=11.0    → Decimal(1) (12.5>11.0)
    i=3 : HA_Close=(13+13+8+8)/4=10.5, HA_Open=(11.0+12.5)/2=11.75     → Decimal(0) (10.5<11.75)
    i=4 : HA_Close=(8+9+7+8)/4=8.0, HA_Open=(11.75+10.5)/2=11.125      → Decimal(0) (8.0<11.125)
    """
    indicator = HeikinAshiIndicator()
    result = indicator.compute(CANDLES_5)
    expected = [None, Decimal(1), Decimal(1), Decimal(0), Decimal(0)]
    assert result == expected


# 3.6b — Vérification manuelle sur 10 bougies
def test_heikin_ashi_manual_10_candles() -> None:
    """Vérification manuelle sur 10 bougies avec tableau HA calculé à la main.

    Tableau de calcul :
    i=0 : (10,12,9,11)  → HA_Close=10.5,  HA_Open[0]=(10+11)/2=10.5           → None
    i=1 : (11,13,10,12) → HA_Close=11.5,  HA_Open=(10.5+10.5)/2=10.5          → Decimal(1)
    i=2 : (12,14,11,13) → HA_Close=12.5,  HA_Open=(10.5+11.5)/2=11.0          → Decimal(1)
    i=3 : (13,13,8,8)   → HA_Close=10.5,  HA_Open=(11.0+12.5)/2=11.75         → Decimal(0)
    i=4 : (8,9,7,8)     → HA_Close=8.0,   HA_Open=(11.75+10.5)/2=11.125       → Decimal(0)
    i=5 : (8,9,7,8)     → HA_Close=8.0,   HA_Open=(11.125+8.0)/2=9.5625       → Decimal(0)
    i=6 : (8,20,8,18)   → HA_Close=13.5,  HA_Open=(9.5625+8.0)/2=8.78125      → Decimal(1)
    i=7 : (18,22,17,21) → HA_Close=19.5,  HA_Open=(8.78125+13.5)/2=11.140625  → Decimal(1)
    i=8 : (21,22,10,10) → HA_Close=15.75, HA_Open=(11.140625+19.5)/2=15.32031 → Decimal(1)
    i=9 : (10,11,5,6)   → HA_Close=8.0,   HA_Open=(15.32031+15.75)/2=15.53516 → Decimal(0)
    """
    indicator = HeikinAshiIndicator()
    result = indicator.compute(CANDLES_10)
    expected = [None, Decimal(1), Decimal(1), Decimal(0), Decimal(0), Decimal(0), Decimal(1), Decimal(1), Decimal(1), Decimal(0)]
    assert result == expected


# 3.7 — Série de bougies haussières
def test_heikin_ashi_bullish_candles() -> None:
    """Série de bougies en hausse → Decimal(1) après la première."""
    indicator = HeikinAshiIndicator()
    # Bougies avec close croissant et high > low clairement pour garantir bullish
    candles = [
        make_candle_ohlc(10, 15, 9, 14),
        make_candle_ohlc(14, 19, 13, 18),
        make_candle_ohlc(18, 23, 17, 22),
        make_candle_ohlc(22, 27, 21, 26),
    ]
    result = indicator.compute(candles)
    assert result[0] is None
    # Toutes les valeurs après la première devraient être bullish (Decimal(1))
    for i in range(1, len(result)):
        assert result[i] == Decimal(1), f"result[{i}] devrait être Decimal(1), obtenu {result[i]}"


# 3.8 — Série de bougies baissières
def test_heikin_ashi_bearish_candles() -> None:
    """Série de bougies en baisse → Decimal(0) après la première."""
    indicator = HeikinAshiIndicator()
    # Bougies avec close décroissant fortement pour garantir bearish
    candles = [
        make_candle_ohlc(30, 31, 25, 26),
        make_candle_ohlc(26, 27, 20, 21),
        make_candle_ohlc(21, 22, 15, 16),
        make_candle_ohlc(16, 17, 10, 11),
    ]
    result = indicator.compute(candles)
    assert result[0] is None
    # Toutes les valeurs après la première devraient être bearish (Decimal(0))
    for i in range(1, len(result)):
        assert result[i] == Decimal(0), f"result[{i}] devrait être Decimal(0), obtenu {result[i]}"


# 3.9 — Marché plat : bougies identiques
def test_heikin_ashi_flat_market() -> None:
    """Bougies identiques → Decimal(0) (neutre = bearish par convention)."""
    indicator = HeikinAshiIndicator()
    # Bougies identiques : HA_Close == HA_Open → Decimal(0)
    candles = [make_candle_ohlc(10, 11, 9, 10) for _ in range(4)]
    result = indicator.compute(candles)
    assert result[0] is None
    for i in range(1, len(result)):
        assert result[i] == Decimal(0), (
            f"result[{i}] devrait être Decimal(0) pour marché plat, obtenu {result[i]}"
        )


# M3 — Invariant BaseIndicator : period <= 0 lève ValueError
def test_heikin_ashi_period_zero_raises_value_error() -> None:
    """period=0 doit lever ValueError (invariant BaseIndicator)."""
    with pytest.raises(ValueError, match="période"):
        HeikinAshiIndicator(period=0)


def test_heikin_ashi_period_negative_raises_value_error() -> None:
    """period=-1 doit lever ValueError (invariant BaseIndicator)."""
    with pytest.raises(ValueError, match="période"):
        HeikinAshiIndicator(period=-1)


# 3.10 — Cas neutre explicite (HA_Close == HA_Open) → Decimal(0)
def test_heikin_ashi_neutral_is_bearish() -> None:
    """Bougie HA_Close == HA_Open → Decimal(0) (bearish par défaut)."""
    indicator = HeikinAshiIndicator()
    # Construire un cas où HA_Close == HA_Open
    # i=0 : open=10, close=10 → HA_Open[0]=(10+10)/2=10, HA_Close[0]=(10+10+10+10)/4=10
    # i=1 : HA_Open[1]=(10+10)/2=10, HA_Close[1]=(10+10+10+10)/4=10 → égal → Decimal(0)
    candles = [
        make_candle_ohlc(10, 10, 10, 10),
        make_candle_ohlc(10, 10, 10, 10),
    ]
    result = indicator.compute(candles)
    assert result[0] is None
    assert result[1] == Decimal(0), "HA_Close == HA_Open devrait retourner Decimal(0)"
