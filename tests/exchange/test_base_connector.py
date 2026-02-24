"""Tests de l'interface abstraite BaseExchangeConnector."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from src.core.event_bus import EventBus
from src.exchange.base import BaseExchangeConnector
from src.models.config import ExchangeConfig
from src.models.exchange import Balance, MarketRules, OrderInfo, OrderSide, OrderType


@pytest.fixture
def exchange_config() -> ExchangeConfig:
    return ExchangeConfig(
        name="binance",
        api_key=SecretStr("test_api_key_123"),
        api_secret=SecretStr("test_api_secret_456"),
        testnet=True,
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


class ConcreteConnector(BaseExchangeConnector):
    """Implementation concrete complete pour les tests."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def watch_candles(self) -> None:
        pass

    async def fetch_market_rules(self, pair: str) -> MarketRules:
        return MarketRules(
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("5"),
            max_leverage=125,
        )

    async def place_order(
        self,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderInfo:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError

    async def set_leverage(self, pair: str, leverage: int) -> None:
        raise NotImplementedError

    async def fetch_balance(self) -> Balance:
        raise NotImplementedError

    async def fetch_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def fetch_open_orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class IncompleteConnector(BaseExchangeConnector):
    """Implementation incomplete — manque des methodes abstraites."""

    async def connect(self) -> None:
        pass


class TestBaseExchangeConnectorAbstract:
    """Tests de l'interface abstraite."""

    def test_cannot_instantiate_base_connector(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """BaseExchangeConnector ne peut pas etre instancie directement."""
        with pytest.raises(TypeError, match="abstract"):
            BaseExchangeConnector(exchange_config, event_bus, "BTC/USDT", "1m")  # type: ignore[abstract]

    def test_concrete_implementation_requires_all_methods(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """Une sous-classe incomplete leve TypeError."""
        with pytest.raises(TypeError, match="abstract"):
            IncompleteConnector(exchange_config, event_bus, "BTC/USDT", "1m")  # type: ignore[abstract]

    def test_concrete_implementation_with_all_methods(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """Une sous-classe complete s'instancie correctement."""
        connector = ConcreteConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        assert connector is not None

    def test_market_rules_property_initially_none(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """market_rules est None apres instanciation."""
        connector = ConcreteConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        assert connector.market_rules is None

    def test_init_stores_config_and_bus(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """Verifie que les attributs sont correctement stockes."""
        connector = ConcreteConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        assert connector._exchange_config is exchange_config
        assert connector._event_bus is event_bus
        assert connector._pair == "BTC/USDT"
        assert connector._timeframe == "1m"

    def test_pair_property_returns_pair(
        self, exchange_config: ExchangeConfig, event_bus: EventBus
    ) -> None:
        """AC5 [M3] : @property pair retourne self._pair via la propriete publique."""
        connector = ConcreteConnector(exchange_config, event_bus, "ETH/USDT", "5m")
        assert connector.pair == "ETH/USDT"
