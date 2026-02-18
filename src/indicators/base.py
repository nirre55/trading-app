"""Interface abstraite pour les indicateurs techniques."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from loguru import logger

from src.models.events import CandleEvent

__all__ = ["BaseIndicator"]


class BaseIndicator(ABC):
    """Interface abstraite pour les indicateurs techniques de trading.

    Les indicateurs sont des calculateurs purs (stateless) :
    - Prennent une liste de bougies en entrée
    - Retournent une liste de valeurs de même longueur
    - Ne s'abonnent PAS au bus d'événements
    - Ne maintiennent PAS d'état entre les appels
    """

    def __init__(self, period: int = 14, **params: Any) -> None:
        if period <= 0:
            raise ValueError(f"La période doit être un entier positif, obtenu : {period}")
        self._period = period
        self._params = params
        logger.debug(
            "{} initialisé — période={}",
            self.__class__.__name__,
            period,
        )

    @property
    def period(self) -> int:
        """Période de calcul de l'indicateur."""
        return self._period

    @abstractmethod
    def compute(self, candles: list[CandleEvent]) -> list[Decimal | None]:
        """Calcule les valeurs de l'indicateur sur les bougies données.

        Args:
            candles: Liste de CandleEvent en ordre chronologique
                     (plus ancien → plus récent).

        Returns:
            Liste de même longueur que candles.
            None pour les bougies où les données sont insuffisantes
            (typiquement les 'period' premières bougies).
        """
