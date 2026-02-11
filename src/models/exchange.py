"""Modèles Pydantic pour les données d'exchange (OHLCV, orderbook, balances)."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class MarketRules(BaseModel):
    """Règles de marché pour une paire de trading."""

    model_config = ConfigDict(strict=False, frozen=False)

    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal
    max_leverage: int


class OrderSide(StrEnum):
    """Côté de l'ordre."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Type d'ordre."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class OrderStatus(StrEnum):
    """Statut d'un ordre."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderInfo(BaseModel):
    """Information complète d'un ordre."""

    model_config = ConfigDict(strict=False, frozen=False)

    id: str
    pair: str
    side: OrderSide
    order_type: OrderType
    price: Decimal | None = None
    quantity: Decimal
    status: OrderStatus
    timestamp: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Balance(BaseModel):
    """Balance du compte sur l'exchange."""

    model_config = ConfigDict(strict=False, frozen=False)

    total: Decimal
    free: Decimal
    used: Decimal
    currency: str = "USDT"

    @model_validator(mode="after")
    def check_total_equals_free_plus_used(self) -> "Balance":
        if self.total != self.free + self.used:
            raise ValueError(
                f"total ({self.total}) != free ({self.free}) + used ({self.used})"
            )
        return self
