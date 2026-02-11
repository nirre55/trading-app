"""Modèles Pydantic pour les trades et ordres."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TradeDirection(StrEnum):
    """Direction du trade."""

    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(StrEnum):
    """Statut du trade."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class TradeRecord(BaseModel):
    """Enregistrement complet d'un trade en cours ou terminé."""

    model_config = ConfigDict(strict=False, frozen=False)

    id: str | UUID
    pair: str
    direction: TradeDirection
    entry_price: Decimal
    exit_price: Decimal | None = None
    stop_loss: Decimal
    take_profit: Decimal
    leverage: int
    quantity: Decimal
    timestamp: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: TradeStatus
    capital_before: Decimal


class TradeResult(BaseModel):
    """Résultat final d'un trade clôturé."""

    model_config = ConfigDict(strict=False, frozen=False)

    trade_id: str
    pair: str
    direction: TradeDirection
    entry_price: Decimal
    exit_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    leverage: int
    pnl: Decimal
    duration: timedelta
    timestamp: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    capital_before: Decimal
    capital_after: Decimal
