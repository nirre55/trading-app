"""Calcul de l'indicateur RSI (Relative Strength Index)."""

from decimal import Decimal

from loguru import logger

from src.indicators.base import BaseIndicator
from src.indicators.registry import IndicatorRegistry
from src.models.events import CandleEvent

__all__ = ["RSIIndicator"]


@IndicatorRegistry.indicator("rsi")
class RSIIndicator(BaseIndicator):
    """Indicateur RSI selon l'algorithme de Wilder (lissage exponentiel)."""

    def compute(self, candles: list[CandleEvent]) -> list[Decimal | None]:
        """Calcule le RSI sur la liste de bougies.

        Retourne None pour les 'period' premières bougies (données insuffisantes).
        Les valeurs suivantes sont dans [0, 100].
        """
        logger.debug(
            "RSI compute — {} bougies, période={}",
            len(candles),
            self._period,
        )

        # Données insuffisantes : besoin d'au moins period+1 bougies
        if len(candles) < self._period + 1:
            return [None] * len(candles)

        closes = [c.close for c in candles]
        period = Decimal(str(self._period))

        # Calcul des variations de prix
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

        # Séparer gains et pertes
        gains = [max(d, Decimal(0)) for d in deltas]
        losses = [abs(min(d, Decimal(0))) for d in deltas]

        # Moyenne initiale simple sur la première période
        avg_gain = sum(gains[: self._period]) / period
        avg_loss = sum(losses[: self._period]) / period

        result: list[Decimal | None] = [None] * self._period

        # Premier RSI (index self._period dans la liste de bougies)
        result.append(self._rsi_from_averages(avg_gain, avg_loss))

        # Lissage Wilder exponentiel pour les bougies suivantes
        for i in range(self._period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            result.append(self._rsi_from_averages(avg_gain, avg_loss))

        return result

    @staticmethod
    def _rsi_from_averages(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
        """Calcule la valeur RSI depuis les moyennes gain/perte."""
        if avg_gain == Decimal(0) and avg_loss == Decimal(0):
            return Decimal(50)  # Marché plat (aucun mouvement) → RSI neutre par convention
        if avg_loss == Decimal(0):
            return Decimal(100)
        rs = avg_gain / avg_loss
        return Decimal(100) - (Decimal(100) / (Decimal(1) + rs))
