"""Modèles Pydantic pour les événements du bus d'événements."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventType(StrEnum):
    """Types d'événements du système, format {domaine}.{action}."""

    # Domaine app
    APP_STARTED = "app.started"
    APP_STOPPED = "app.stopped"

    # Domaine exchange
    EXCHANGE_CONNECTED = "exchange.connected"
    EXCHANGE_DISCONNECTED = "exchange.disconnected"
    EXCHANGE_RECONNECTED = "exchange.reconnected"

    # Domaine candle
    CANDLE_CLOSED = "candle.closed"

    # Domaine strategy
    STRATEGY_CONDITION_MET = "strategy.condition_met"
    STRATEGY_SIGNAL_LONG = "strategy.signal_long"
    STRATEGY_SIGNAL_SHORT = "strategy.signal_short"
    STRATEGY_TIMEOUT = "strategy.timeout"

    # Domaine trade
    TRADE_OPENED = "trade.opened"
    TRADE_FAILED = "trade.failed"
    TRADE_TP_HIT = "trade.tp_hit"
    TRADE_SL_HIT = "trade.sl_hit"
    TRADE_CLOSED = "trade.closed"

    # Domaine error
    ERROR_RECOVERABLE = "error.recoverable"
    ERROR_CRITICAL = "error.critical"


class BaseEvent(BaseModel):
    """Événement de base avec type et timestamp UTC obligatoire."""

    model_config = ConfigDict(strict=False, frozen=False)

    event_type: EventType
    timestamp: AwareDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AppEvent(BaseEvent):
    """Événement du domaine application."""

    reason: str | None = None

    @model_validator(mode="after")
    def check_domain(self) -> "AppEvent":
        if not self.event_type.value.startswith("app."):
            raise ValueError(f"AppEvent requiert un event_type 'app.*', reçu '{self.event_type.value}'")
        return self


class ExchangeEvent(BaseEvent):
    """Événement du domaine exchange."""

    exchange_name: str
    details: str | None = None

    @model_validator(mode="after")
    def check_domain(self) -> "ExchangeEvent":
        if not self.event_type.value.startswith("exchange."):
            raise ValueError(f"ExchangeEvent requiert un event_type 'exchange.*', reçu '{self.event_type.value}'")
        return self


class CandleEvent(BaseEvent):
    """Événement du domaine candle."""

    pair: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @model_validator(mode="after")
    def check_domain(self) -> "CandleEvent":
        if not self.event_type.value.startswith("candle."):
            raise ValueError(f"CandleEvent requiert un event_type 'candle.*', reçu '{self.event_type.value}'")
        return self


class StrategyEvent(BaseEvent):
    """Événement du domaine strategy."""

    strategy_name: str
    pair: str
    condition_index: int | None = None
    details: str | None = None
    signal_price: Decimal | None = None
    sl_price: Decimal | None = None

    @model_validator(mode="after")
    def check_domain(self) -> "StrategyEvent":
        if not self.event_type.value.startswith("strategy."):
            raise ValueError(f"StrategyEvent requiert un event_type 'strategy.*', reçu '{self.event_type.value}'")
        return self


class TradeEvent(BaseEvent):
    """Événement du domaine trade."""

    trade_id: str
    pair: str
    details: str | None = None
    exit_price: Decimal | None = None
    pnl: Decimal | None = None
    capital_before: Decimal | None = None
    capital_after: Decimal | None = None

    @model_validator(mode="after")
    def check_domain(self) -> "TradeEvent":
        if not self.event_type.value.startswith("trade."):
            raise ValueError(f"TradeEvent requiert un event_type 'trade.*', reçu '{self.event_type.value}'")
        return self


class ErrorEvent(BaseEvent):
    """Événement du domaine error."""

    error_type: str
    message: str
    traceback: str | None = None

    @model_validator(mode="after")
    def check_domain(self) -> "ErrorEvent":
        if not self.event_type.value.startswith("error."):
            raise ValueError(f"ErrorEvent requiert un event_type 'error.*', reçu '{self.event_type.value}'")
        return self
