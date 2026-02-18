"""Stratégie exemple démontrant le pattern de conditions séquentielles."""

from loguru import logger

from src.models.config import ConditionConfig
from src.models.events import CandleEvent
from src.strategies.base import BaseStrategy
from src.strategies.registry import StrategyRegistry

__all__ = ["ExampleStrategy"]


@StrategyRegistry.strategy("example")
class ExampleStrategy(BaseStrategy):
    """Stratégie exemple avec conditions séquentielles configurées via YAML."""

    async def evaluate_conditions(self, candle: CandleEvent) -> None:
        """Évalue les conditions séquentielles sur la bougie courante."""
        conditions = self._config.conditions
        conditions_met_count = len(self._state_machine.conditions_met)

        # Vérifier le gap depuis la dernière condition si au moins une est satisfaite
        if conditions_met_count > 0 and self._is_gap_exceeded(conditions_met_count):
            logger.info(
                "Stratégie '{}' : timeout après {} bougies depuis la condition #{}",
                self._config.name,
                self._candle_count - self._last_condition_candle,
                conditions_met_count - 1,
            )
            await self._state_machine.on_timeout()
            self._last_condition_candle = 0
            return

        # Évaluer la prochaine condition dans la séquence
        if conditions_met_count >= len(conditions):
            return

        next_condition = conditions[conditions_met_count]
        if self._evaluate_single_condition(next_condition, candle):
            await self._state_machine.on_condition_met(
                conditions_met_count, self._candle_count
            )
            self._last_condition_candle = self._candle_count

            # Vérifier si toutes les conditions sont satisfaites
            if len(self._state_machine.conditions_met) == len(conditions):
                await self._state_machine.on_all_conditions_met(self.get_signal())

    def _evaluate_single_condition(
        self, condition: ConditionConfig, candle: CandleEvent
    ) -> bool:
        """Évalue une condition individuelle.

        Dans une vraie stratégie, utiliser la bibliothèque d'indicateurs (Story 3.3).
        Pour l'exemple, utilise le paramètre 'always_true' pour les tests.
        """
        return bool(condition.params.get("always_true", False))

    def get_signal(self) -> str:
        """Retourne la direction du signal : 'long' par défaut dans l'exemple."""
        return "long"

