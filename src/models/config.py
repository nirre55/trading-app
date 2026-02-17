"""Modèles Pydantic pour la configuration de l'application."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


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


class DefaultsConfig(BaseModel):
    """Configuration des valeurs par défaut."""

    model_config = ConfigDict(strict=False, frozen=False)

    log_level: str = "INFO"
    risk_percent: float = Field(default=1.0)


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
