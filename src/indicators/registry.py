"""Registre dynamique des indicateurs techniques disponibles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.core.exceptions import ConfigError

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.indicators.base import BaseIndicator

__all__ = ["IndicatorRegistry"]


class IndicatorRegistry:
    """Registre central des indicateurs techniques disponibles."""

    _registry: dict[str, type[BaseIndicator]] = {}

    @classmethod
    def register(cls, name: str, indicator_class: type[BaseIndicator]) -> None:
        """Enregistre un indicateur dans le registre."""
        if name in cls._registry:
            logger.warning(
                "Indicateur '{}' écrase une entrée existante : {} → {}",
                name,
                cls._registry[name].__name__,
                indicator_class.__name__,
            )
        cls._registry[name] = indicator_class
        logger.debug("Indicateur '{}' enregistré dans le registre", name)

    @classmethod
    def get(cls, name: str) -> type[BaseIndicator]:
        """Retourne la classe d'indicateur par son nom.

        Raises:
            ConfigError: Si l'indicateur n'est pas enregistré.
        """
        if name not in cls._registry:
            available = list(cls._registry.keys())
            msg = (
                f"Indicateur '{name}' introuvable dans le registre. "
                f"Disponibles : {available}"
            )
            logger.error("IndicatorRegistry — {}", msg)
            raise ConfigError(msg, context={"name": name, "available": available})
        return cls._registry[name]

    @classmethod
    def list_available(cls) -> list[str]:
        """Retourne la liste des indicateurs enregistrés."""
        return list(cls._registry.keys())

    @classmethod
    def indicator(
        cls, name: str
    ) -> Callable[[type[BaseIndicator]], type[BaseIndicator]]:
        """Décorateur d'enregistrement automatique d'un indicateur dans le registre.

        Usage:
            @IndicatorRegistry.indicator("rsi")
            class RSIIndicator(BaseIndicator):
                ...
        """

        def decorator(indicator_class: type[BaseIndicator]) -> type[BaseIndicator]:
            cls.register(name, indicator_class)
            return indicator_class

        return decorator
