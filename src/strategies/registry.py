"""Registre dynamique des stratégies disponibles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.core.exceptions import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.strategies.base import BaseStrategy

__all__ = ["StrategyRegistry"]


class StrategyRegistry:
    """Registre central des plugins de stratégie disponibles."""

    _registry: dict[str, type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type[BaseStrategy]) -> None:
        """Enregistre une stratégie dans le registre."""
        cls._registry[name] = strategy_class
        logger.debug("Stratégie '{}' enregistrée dans le registre", name)

    @classmethod
    def get(cls, name: str) -> type[BaseStrategy]:
        """Retourne la classe de stratégie par son nom.

        Raises:
            ConfigError: Si la stratégie n'est pas enregistrée.
        """
        if name not in cls._registry:
            available = list(cls._registry.keys())
            msg = (
                f"Stratégie '{name}' introuvable dans le registre. "
                f"Disponibles : {available}"
            )
            logger.error("StrategyRegistry — {}", msg)
            raise ConfigError(msg, context={"name": name, "available": available})
        return cls._registry[name]

    @classmethod
    def list_available(cls) -> list[str]:
        """Retourne la liste des stratégies enregistrées."""
        return list(cls._registry.keys())

    @classmethod
    def strategy(cls, name: str) -> Callable[[type[BaseStrategy]], type[BaseStrategy]]:
        """Décorateur d'enregistrement automatique d'une stratégie dans le registre.

        Usage:
            @StrategyRegistry.strategy("ma_strategie")
            class MaStrategie(BaseStrategy):
                ...
        """

        def decorator(strategy_class: type[BaseStrategy]) -> type[BaseStrategy]:
            cls.register(name, strategy_class)
            return strategy_class

        return decorator
