"""Modèles Pydantic pour la configuration de l'application."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

__all__ = [
    "ExchangeConfig",
    "PathsConfig",
    "DefaultsConfig",
    "AppConfig",
    "ConditionConfig",
    "CapitalConfig",
    "StrategyConfig",
]

_MARTINGALE_MODES = frozenset({"martingale", "martingale_inverse"})


class ExchangeConfig(BaseModel):
    """Configuration de connexion à l'exchange."""

    model_config = ConfigDict(strict=False, frozen=False)

    name: str
    api_key: SecretStr
    api_secret: SecretStr
    password: SecretStr | None = None
    testnet: bool = True


class PathsConfig(BaseModel):
    """Configuration des chemins de fichiers."""

    model_config = ConfigDict(strict=False, frozen=False)

    logs: str
    trades: str
    state: str
    backup: str = "data/backups"


class DefaultsConfig(BaseModel):
    """Configuration des valeurs par défaut."""

    model_config = ConfigDict(strict=False, frozen=False)

    log_level: str = "INFO"
    risk_percent: float = Field(default=1.0)
    backup_interval_hours: int = Field(default=24, gt=0)


class AppConfig(BaseModel):
    """Configuration principale de l'application."""

    model_config = ConfigDict(strict=False, frozen=False)

    exchange: ExchangeConfig
    paths: PathsConfig
    defaults: DefaultsConfig


class ConditionConfig(BaseModel):
    """Configuration d'une condition de stratégie."""

    model_config = ConfigDict(strict=False, frozen=False)

    type: str
    params: dict[str, Any]
    max_gap_candles: int | None = None


class CapitalConfig(BaseModel):
    """Configuration de la gestion du capital."""

    model_config = ConfigDict(strict=False, frozen=False)

    mode: str
    risk_percent: float
    risk_reward_ratio: float
    factor: float | None = None
    max_steps: int | None = None

    @model_validator(mode="after")
    def _validate_martingale_fields(self) -> CapitalConfig:
        if self.mode in _MARTINGALE_MODES:
            if self.factor is None:
                raise ValueError(
                    f"Le champ 'factor' est requis pour le mode '{self.mode}'"
                )
        if self.factor is not None and (not math.isfinite(self.factor) or self.factor <= 0):
            raise ValueError("'factor' doit être un nombre fini strictement positif (> 0)")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("'max_steps' doit être strictement positif (> 0)")
        return self


class StrategyConfig(BaseModel):
    """Configuration complète d'une stratégie de trading."""

    model_config = ConfigDict(strict=False, frozen=False)

    name: str
    pair: str
    exchange: str
    timeframe: str
    leverage: int
    conditions: list[ConditionConfig]
    timeout_candles: int
    capital: CapitalConfig
