"""Tests du connecteur CCXT Pro avec exchange mocke."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import ccxt
import pytest
from pydantic import SecretStr

from src.core.event_bus import EventBus
from src.core.exceptions import ExchangeConnectionError, ExchangeError
from src.exchange.ccxt_connector import CcxtConnector
from src.models.config import ExchangeConfig
from src.models.events import EventType


@pytest.fixture
def exchange_config() -> ExchangeConfig:
    return ExchangeConfig(
        name="binance",
        api_key=SecretStr("test_api_key_123"),
        api_secret=SecretStr("test_api_secret_456"),
        testnet=True,
    )


@pytest.fixture
def exchange_config_no_testnet() -> ExchangeConfig:
    return ExchangeConfig(
        name="binance",
        api_key=SecretStr("test_api_key_123"),
        api_secret=SecretStr("test_api_secret_456"),
        testnet=False,
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_ccxt_exchange():
    """Mock complet d'une instance CCXT Pro exchange."""
    exchange = AsyncMock()
    exchange.markets = {
        "BTC/USDT": {
            "precision": {"amount": 0.001, "price": 0.01},
            "limits": {
                "cost": {"min": 5.0},
                "leverage": {"max": 125},
                "amount": {"min": 0.001, "max": 1000.0},
            },
        },
    }
    exchange.load_markets = AsyncMock(return_value=exchange.markets)
    exchange.close = AsyncMock()
    exchange.set_sandbox_mode = MagicMock()
    return exchange


@pytest.fixture
def mock_ccxt_pro(mock_ccxt_exchange):
    """Patch ccxt.pro pour retourner le mock exchange."""
    mock_exchange_class = MagicMock(return_value=mock_ccxt_exchange)
    with patch("src.exchange.ccxt_connector.ccxt.pro") as mock_pro:
        mock_pro.binance = mock_exchange_class
        yield mock_pro


class TestCcxtConnectorConnect:
    """Tests de la methode connect()."""

    @pytest.mark.asyncio
    async def test_connect_initializes_exchange(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """connect() cree l'instance CCXT Pro avec les bons parametres."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        # Verifie que getattr(ccxt.pro, "binance") a ete appele
        exchange_class = getattr(mock_ccxt_pro, "binance")
        exchange_class.assert_called_once()
        call_kwargs = exchange_class.call_args[0][0]
        assert call_kwargs["apiKey"] == "test_api_key_123"
        assert call_kwargs["secret"] == "test_api_secret_456"
        assert call_kwargs["enableRateLimit"] is True
        assert call_kwargs["options"]["defaultType"] == "future"

    @pytest.mark.asyncio
    async def test_connect_sets_sandbox_mode(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Avec testnet=True, set_sandbox_mode(True) est appele."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        mock_ccxt_exchange.set_sandbox_mode.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_connect_no_sandbox_mode_when_not_testnet(
        self,
        exchange_config_no_testnet: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Avec testnet=False, set_sandbox_mode n'est pas appele."""
        connector = CcxtConnector(exchange_config_no_testnet, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        mock_ccxt_exchange.set_sandbox_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_loads_markets(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """connect() appelle load_markets()."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        mock_ccxt_exchange.load_markets.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_fetches_market_rules(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Apres connect(), market_rules n'est plus None et contient les bonnes valeurs."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        assert connector.market_rules is not None
        assert connector.market_rules.step_size == Decimal("0.001")
        assert connector.market_rules.tick_size == Decimal("0.01")
        assert connector.market_rules.min_notional == Decimal("5")
        assert connector.market_rules.max_leverage == 125

    @pytest.mark.asyncio
    async def test_connect_emits_connected_event(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """connect() emet EventType.EXCHANGE_CONNECTED avec un ExchangeEvent."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.EXCHANGE_CONNECTED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        assert len(received_events) == 1
        assert received_events[0].exchange_name == "binance"
        assert received_events[0].event_type == EventType.EXCHANGE_CONNECTED

    @pytest.mark.asyncio
    async def test_connect_failure_raises_connection_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Si load_markets() echoue, ExchangeConnectionError est levee."""
        mock_ccxt_exchange.load_markets.side_effect = Exception("Network error")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")

        with pytest.raises(ExchangeConnectionError, match="binance"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_connect_invalid_exchange_name_raises_connection_error(
        self,
        event_bus: EventBus,
    ) -> None:
        """Nom d'exchange invalide leve ExchangeConnectionError."""
        config = ExchangeConfig(
            name="exchange_inexistant",
            api_key=SecretStr("key"),
            api_secret=SecretStr("secret"),
            testnet=False,
        )
        connector = CcxtConnector(config, event_bus, "BTC/USDT", "1m")

        with pytest.raises(ExchangeConnectionError, match="exchange_inexistant"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_connect_ccxt_network_error_raises_connection_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.NetworkError est mappe vers ExchangeConnectionError."""
        mock_ccxt_exchange.load_markets.side_effect = ccxt.NetworkError("timeout")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")

        with pytest.raises(ExchangeConnectionError, match="binance"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_connect_ccxt_auth_error_raises_connection_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.AuthenticationError est mappe vers ExchangeConnectionError."""
        mock_ccxt_exchange.load_markets.side_effect = ccxt.AuthenticationError("invalid key")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")

        with pytest.raises(ExchangeConnectionError, match="binance"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_connect_ccxt_base_error_raises_exchange_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.BaseError generique est mappe vers ExchangeError."""
        mock_ccxt_exchange.load_markets.side_effect = ccxt.BaseError("unknown error")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")

        with pytest.raises(ExchangeError, match="binance"):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_connect_double_call_disconnects_first(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Un double appel a connect() deconnecte l'instance precedente."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()

        # Premier close appele lors du disconnect automatique
        mock_ccxt_exchange.close.assert_not_awaited()

        await connector.connect()

        # close() doit avoir ete appele pour fermer la premiere connexion
        mock_ccxt_exchange.close.assert_awaited_once()


class TestCcxtConnectorDisconnect:
    """Tests de la methode disconnect()."""

    @pytest.mark.asyncio
    async def test_disconnect_closes_exchange(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """disconnect() appelle exchange.close()."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()
        await connector.disconnect()

        mock_ccxt_exchange.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_emits_disconnected_event(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """disconnect() emet EventType.EXCHANGE_DISCONNECTED."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.EXCHANGE_DISCONNECTED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()
        await connector.disconnect()

        assert len(received_events) == 1
        assert received_events[0].exchange_name == "binance"
        assert received_events[0].event_type == EventType.EXCHANGE_DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_without_connect_no_event(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ) -> None:
        """disconnect() sans connect() prealable n'emet pas d'evenement."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.EXCHANGE_DISCONNECTED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.disconnect()

        assert len(received_events) == 0

    @pytest.mark.asyncio
    async def test_disconnect_resets_exchange_to_none(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """disconnect() remet _exchange a None."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        await connector.connect()
        assert connector._exchange is not None

        await connector.disconnect()
        assert connector._exchange is None


class TestCcxtConnectorWatchCandles:
    """Tests de la methode watch_candles()."""

    @pytest.mark.asyncio
    async def test_watch_candles_emits_closed_candle(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Verifie que watch_candles emet un CandleEvent quand une bougie se ferme."""
        call_count = 0

        async def mock_watch_ohlcv(symbol, timeframe, since=None, limit=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[1700000000000, 42000.0, 42500.0, 41800.0, 42200.0, 100.0]]
            elif call_count == 2:
                return [
                    [1700000000000, 42000.0, 42500.0, 41800.0, 42200.0, 150.0],
                    [1700000060000, 42200.0, 42300.0, 42100.0, 42250.0, 50.0],
                ]
            else:
                raise asyncio.CancelledError()

        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)

        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.CANDLE_CLOSED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(asyncio.CancelledError):
            await connector.watch_candles()

        assert len(received_events) == 1
        candle_event = received_events[0]
        assert candle_event.pair == "BTC/USDT"
        assert candle_event.timeframe == "1m"
        assert candle_event.close == Decimal("42200.0")
        assert candle_event.volume == Decimal("150.0")

    @pytest.mark.asyncio
    async def test_watch_candles_skips_first_candle(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Au premier appel, aucun evenement n'est emis (initialisation)."""
        call_count = 0

        async def mock_watch_ohlcv(symbol, timeframe, since=None, limit=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[1700000000000, 42000.0, 42500.0, 41800.0, 42200.0, 100.0]]
            else:
                raise asyncio.CancelledError()

        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)

        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.CANDLE_CLOSED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(asyncio.CancelledError):
            await connector.watch_candles()

        assert len(received_events) == 0

    @pytest.mark.asyncio
    async def test_watch_candles_handles_cancellation(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """asyncio.CancelledError est propage proprement."""
        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=asyncio.CancelledError())

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(asyncio.CancelledError):
            await connector.watch_candles()

    @pytest.mark.asyncio
    async def test_watch_candles_skips_empty_ohlcv(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """watch_candles continue si watch_ohlcv retourne une liste vide."""
        call_count = 0

        async def mock_watch_ohlcv(symbol, timeframe, since=None, limit=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            else:
                raise asyncio.CancelledError()

        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)

        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.on(EventType.CANDLE_CLOSED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(asyncio.CancelledError):
            await connector.watch_candles()

        assert len(received_events) == 0


class TestCcxtConnectorFetchMarketRules:
    """Tests de la methode fetch_market_rules()."""

    @pytest.mark.asyncio
    async def test_fetch_market_rules_returns_correct_values(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Verifier step_size, tick_size, min_notional, max_leverage."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        rules = await connector.fetch_market_rules("BTC/USDT")

        assert rules.step_size == Decimal("0.001")
        assert rules.tick_size == Decimal("0.01")
        assert rules.min_notional == Decimal("5")
        assert rules.max_leverage == 125

    @pytest.mark.asyncio
    async def test_fetch_market_rules_unknown_pair_raises_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Paire inconnue leve ExchangeError."""
        from src.core.exceptions import ExchangeError

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(ExchangeError, match="ETH/USDT"):
            await connector.fetch_market_rules("ETH/USDT")

    @pytest.mark.asyncio
    async def test_fetch_market_rules_none_min_notional(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """min_notional None est converti en Decimal('0')."""
        mock_ccxt_exchange.markets["BTC/USDT"]["limits"]["cost"]["min"] = None

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        rules = await connector.fetch_market_rules("BTC/USDT")
        assert rules.min_notional == Decimal("0")

    @pytest.mark.asyncio
    async def test_fetch_market_rules_none_max_leverage(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """max_leverage None est converti en 1."""
        mock_ccxt_exchange.markets["BTC/USDT"]["limits"]["leverage"]["max"] = None

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        rules = await connector.fetch_market_rules("BTC/USDT")
        assert rules.max_leverage == 1


class TestCcxtConnectorStubs:
    """Tests des stubs NotImplementedError."""

    @pytest.mark.asyncio
    async def test_place_order_raises_not_implemented(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ) -> None:
        """place_order() leve NotImplementedError."""
        from src.models.exchange import OrderSide, OrderType

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        with pytest.raises(NotImplementedError):
            await connector.place_order(
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.1"),
            )

    @pytest.mark.asyncio
    async def test_cancel_order_raises_not_implemented(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ) -> None:
        """cancel_order() leve NotImplementedError."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        with pytest.raises(NotImplementedError):
            await connector.cancel_order("order-123")

    @pytest.mark.asyncio
    async def test_fetch_balance_raises_not_implemented(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ) -> None:
        """fetch_balance() leve NotImplementedError."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        with pytest.raises(NotImplementedError):
            await connector.fetch_balance()

    @pytest.mark.asyncio
    async def test_fetch_positions_raises_not_implemented(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ) -> None:
        """fetch_positions() leve NotImplementedError."""
        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        with pytest.raises(NotImplementedError):
            await connector.fetch_positions()
