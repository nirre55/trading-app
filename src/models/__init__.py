"""Exports publics de tous les modèles Pydantic de trading-app."""

from src.models.config import (
    AppConfig,
    CapitalConfig,
    ConditionConfig,
    DefaultsConfig,
    ExchangeConfig,
    PathsConfig,
    StrategyConfig,
)
from src.models.events import (
    AppEvent,
    BaseEvent,
    CandleEvent,
    ErrorEvent,
    EventType,
    ExchangeEvent,
    StrategyEvent,
    TradeEvent,
)
from src.models.exchange import (
    Balance,
    MarketRules,
    OrderInfo,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.models.state import AppState, StrategyState, StrategyStateEnum
from src.models.trade import TradeDirection, TradeRecord, TradeResult, TradeStatus

__all__ = [
    # Events
    "EventType",
    "BaseEvent",
    "AppEvent",
    "ExchangeEvent",
    "CandleEvent",
    "StrategyEvent",
    "TradeEvent",
    "ErrorEvent",
    # Config
    "ExchangeConfig",
    "PathsConfig",
    "DefaultsConfig",
    "AppConfig",
    "ConditionConfig",
    "CapitalConfig",
    "StrategyConfig",
    # Trade
    "TradeDirection",
    "TradeStatus",
    "TradeRecord",
    "TradeResult",
    # State
    "StrategyStateEnum",
    "StrategyState",
    "AppState",
    # Exchange
    "MarketRules",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "OrderInfo",
    "Balance",
]
