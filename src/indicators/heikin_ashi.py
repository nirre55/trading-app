"""Calcul de l'indicateur Heikin-Ashi (direction de tendance)."""

from decimal import Decimal
from typing import Any

from loguru import logger

from src.indicators.base import BaseIndicator
from src.indicators.registry import IndicatorRegistry
from src.models.events import CandleEvent

__all__ = ["HeikinAshiIndicator"]


@IndicatorRegistry.indicator("heikin_ashi")
class HeikinAshiIndicator(BaseIndicator):
    """Indicateur Heikin-Ashi — direction de tendance des bougies.

    Retourne Decimal(1) si la bougie HA est bullish (HA_Close > HA_Open),
    Decimal(0) si bearish ou neutre (HA_Close <= HA_Open).
    La première bougie retourne toujours None (HA_Open nécessite une bougie précédente).
    """

    def __init__(self, period: int = 1, **params: Any) -> None:
        """Initialise l'indicateur Heikin-Ashi.

        Note : la période n'influe pas sur le calcul — HA_Open[i] dépend
        uniquement de la bougie précédente (i-1), quelle que soit la valeur de period.
        """
        super().__init__(period=period, **params)

    def compute(self, candles: list[CandleEvent]) -> list[Decimal | None]:
        """Calcule la direction Heikin-Ashi pour chaque bougie."""
        logger.debug("HeikinAshi compute — {} bougies", len(candles))

        if len(candles) == 0:
            return []

        result: list[Decimal | None] = []
        ha_open_prev = Decimal(0)
        ha_close_prev = Decimal(0)

        for i, candle in enumerate(candles):
            ha_close = (candle.open + candle.high + candle.low + candle.close) / Decimal(4)

            if i == 0:
                # Initialisation : HA_Open[0] = (open[0] + close[0]) / 2
                ha_open_prev = (candle.open + candle.close) / Decimal(2)
                ha_close_prev = ha_close
                result.append(None)
            else:
                ha_open = (ha_open_prev + ha_close_prev) / Decimal(2)
                # AC 3 : formules Heikin-Ashi standards complètes
                ha_high = max(candle.high, ha_open, ha_close)
                ha_low = min(candle.low, ha_open, ha_close)
                direction = Decimal(1) if ha_close > ha_open else Decimal(0)
                logger.debug(
                    "HA i={} open={} close={} high={} low={} dir={}",
                    i, ha_open, ha_close, ha_high, ha_low, direction,
                )
                result.append(direction)
                ha_open_prev = ha_open
                ha_close_prev = ha_close

        return result
