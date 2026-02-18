"""Interface abstraite pour les plugins de stratégie de trading."""

from abc import ABC, abstractmethod

from loguru import logger

from src.core.event_bus import EventBus
from src.core.state_machine import StateMachine
from src.models.config import StrategyConfig
from src.models.events import CandleEvent, EventType
from src.models.state import StrategyStateEnum

__all__ = ["BaseStrategy"]


class BaseStrategy(ABC):
    """Interface abstraite pour les plugins de stratégie de trading."""

    def __init__(
        self,
        config: StrategyConfig,
        state_machine: StateMachine,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._state_machine = state_machine
        self._bus = event_bus
        self._candle_count: int = 0
        self._last_condition_candle: int = 0
        self._on_candle_bound = self.on_candle
        event_bus.on(EventType.CANDLE_CLOSED, self._on_candle_bound)  # type: ignore[arg-type]
        logger.debug(
            "Stratégie '{}' initialisée — {} condition(s), timeout={} bougies",
            config.name,
            len(config.conditions),
            config.timeout_candles,
        )

    @property
    def candle_count(self) -> int:
        """Nombre total de bougies reçues depuis le démarrage."""
        return self._candle_count

    @property
    def last_condition_candle(self) -> int:
        """Index de bougie de la dernière condition satisfaite."""
        return self._last_condition_candle

    @abstractmethod
    async def evaluate_conditions(self, candle: CandleEvent) -> None:
        """Évalue les conditions de la stratégie sur la bougie courante.

        Appelée par on_candle() uniquement si l'état n'est pas IN_TRADE ou SIGNAL_READY.
        L'implémentation doit :
        1. Déterminer la prochaine condition à évaluer
        2. Vérifier le gap timeout si au moins une condition est déjà satisfaite
        3. Évaluer la prochaine condition
        4. Appeler state_machine.on_condition_met() si satisfaite
        5. Appeler state_machine.on_all_conditions_met() si toutes satisfaites
        """

    @abstractmethod
    def get_signal(self) -> str:
        """Retourne la direction du signal : 'long' ou 'short'."""

    async def on_candle(self, candle: CandleEvent) -> None:
        """Handler bus CANDLE_CLOSED — orchestre l'évaluation des conditions."""
        self._candle_count += 1
        current_state = self._state_machine.state
        if current_state in (StrategyStateEnum.IN_TRADE, StrategyStateEnum.SIGNAL_READY):
            logger.debug(
                "Stratégie '{}' : bougie #{} ignorée (état={})",
                self._config.name,
                self._candle_count,
                current_state,
            )
            return
        await self.evaluate_conditions(candle)

    def _get_max_gap(self, condition_index: int) -> int:
        """Retourne le gap max pour la condition donnée.

        Utilise max_gap_candles de la condition si défini,
        sinon utilise timeout_candles de la config globale.
        """
        if condition_index < len(self._config.conditions):
            condition = self._config.conditions[condition_index]
            if condition.max_gap_candles is not None:
                return condition.max_gap_candles
        return self._config.timeout_candles

    def _is_gap_exceeded(self, condition_index: int) -> bool:
        """Vérifie si le gap depuis la dernière condition satisfaite est dépassé."""
        if self._last_condition_candle == 0:
            return False
        gap = self._candle_count - self._last_condition_candle
        max_gap = self._get_max_gap(condition_index)
        return gap > max_gap

    def stop(self) -> None:
        """Désabonne la stratégie du bus CANDLE_CLOSED — libère les ressources."""
        self._bus.off(EventType.CANDLE_CLOSED, self._on_candle_bound)  # type: ignore[arg-type]
        logger.debug("Stratégie '{}' désabonnée du bus", self._config.name)
