"""Hiérarchie d'exceptions custom pour trading-app."""

from typing import Any

__all__ = [
    "TradingAppError",
    "ExchangeError",
    "ExchangeConnectionError",
    "RateLimitError",
    "TradeError",
    "OrderFailedError",
    "InsufficientBalanceError",
    "ConfigError",
    "DataValidationError",
    "LockError",
]


class TradingAppError(Exception):
    """Classe de base pour toutes les exceptions de trading-app."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


class ExchangeError(TradingAppError):
    """Erreurs liées à la connectivité et aux opérations exchange."""


class ExchangeConnectionError(ExchangeError):
    """Perte de connexion WebSocket avec l'exchange."""


class RateLimitError(ExchangeError):
    """Rate limiting API de l'exchange."""


class TradeError(TradingAppError):
    """Erreurs liées à l'exécution de trades."""


class OrderFailedError(TradeError):
    """Échec d'envoi d'un ordre à l'exchange."""


class InsufficientBalanceError(TradeError):
    """Balance insuffisante pour exécuter l'ordre."""


class ConfigError(TradingAppError):
    """Erreurs de configuration de l'application."""


class DataValidationError(TradingAppError):
    """Erreurs de validation des données."""


class LockError(TradingAppError):
    """Instance déjà active détectée via fichier de lock."""
