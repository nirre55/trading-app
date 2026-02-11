"""Modèles Pydantic pour l'état persistant de l'application."""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrategyStateEnum(StrEnum):
    """États possibles de la machine à états de stratégie."""

    IDLE = "IDLE"
    WATCHING = "WATCHING"
    SIGNAL_READY = "SIGNAL_READY"
    IN_TRADE = "IN_TRADE"


class StrategyState(BaseModel):
    """État courant d'une stratégie, sérialisable pour recovery."""

    model_config = ConfigDict(strict=False, frozen=False)

    state: StrategyStateEnum
    conditions_met: list[int] = Field(default_factory=list)
    last_condition_candle: int | None = None
    current_trade_id: str | None = None
    timestamp: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AppState(BaseModel):
    """État global de l'application, sérialisable pour crash recovery."""

    model_config = ConfigDict(strict=False, frozen=False)

    strategy_states: dict[str, StrategyState] = Field(default_factory=dict)
    active_trades: list[str] = Field(default_factory=list)
    last_candle_timestamp: AwareDatetime | None = None
    uptime_start: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
