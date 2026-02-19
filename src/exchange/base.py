"""Interface abstraite pour les connecteurs d'exchange."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.core.event_bus import EventBus
from src.models.config import ExchangeConfig
from src.models.exchange import Balance, MarketRules, OrderInfo, OrderSide, OrderType

__all__ = ["BaseExchangeConnector"]


class BaseExchangeConnector(ABC):
    """Interface abstraite pour les connecteurs d'exchange."""

    def __init__(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        pair: str,
        timeframe: str,
    ) -> None:
        self._exchange_config = exchange_config
        self._event_bus = event_bus
        self._pair = pair
        self._timeframe = timeframe
        self._market_rules: MarketRules | None = None

    @property
    def market_rules(self) -> MarketRules | None:
        """Retourne les regles de marche chargees, ou None si pas encore chargees."""
        return self._market_rules

    @property
    def pair(self) -> str:
        """Retourne la paire de trading du connecteur."""
        return self._pair

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def watch_candles(self) -> None: ...

    @abstractmethod
    async def fetch_market_rules(self, pair: str) -> MarketRules: ...

    @abstractmethod
    async def place_order(
        self,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderInfo: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    async def set_leverage(self, pair: str, leverage: int) -> None: ...

    @abstractmethod
    async def fetch_balance(self) -> Balance: ...

    @abstractmethod
    async def fetch_positions(self) -> list[dict[str, Any]]: ...
