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


class TestCcxtConnectorReconnect:
    """Tests de la logique d'auto-reconnexion."""

    @pytest.mark.asyncio
    async def test_watch_candles_reconnects_on_network_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Apres NetworkError, watch_candles reprend et emet EXCHANGE_DISCONNECTED puis EXCHANGE_RECONNECTED."""
        call_count = 0

        async def mock_watch_ohlcv(symbol, timeframe, since=None, limit=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [[1700000000000, 42000.0, 42500.0, 41800.0, 42200.0, 100.0]]
            elif call_count == 2:
                raise ccxt.NetworkError("Connection lost")
            elif call_count == 3:
                return [
                    [1700000000000, 42000.0, 42500.0, 41800.0, 42200.0, 150.0],
                    [1700000060000, 42200.0, 42300.0, 42100.0, 42250.0, 50.0],
                ]
            else:
                raise asyncio.CancelledError()

        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        reconnected_events = []
        disconnected_events = []

        async def reconnected_handler(event):
            reconnected_events.append(event)

        async def disconnected_handler(event):
            disconnected_events.append(event)

        event_bus.on(EventType.EXCHANGE_RECONNECTED, reconnected_handler)
        event_bus.on(EventType.EXCHANGE_DISCONNECTED, disconnected_handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange
        connector._is_connected = True

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await connector.watch_candles()

        assert len(disconnected_events) == 1
        assert disconnected_events[0].exchange_name == "binance"
        assert len(reconnected_events) == 1
        assert reconnected_events[0].exchange_name == "binance"

    @pytest.mark.asyncio
    async def test_reconnect_emits_reconnected_event(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """_reconnect() emet EXCHANGE_RECONNECTED avec un ExchangeEvent."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        reconnected_events = []

        async def handler(event):
            reconnected_events.append(event)

        event_bus.on(EventType.EXCHANGE_RECONNECTED, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            await connector._reconnect()

        assert len(reconnected_events) == 1
        assert reconnected_events[0].event_type == EventType.EXCHANGE_RECONNECTED
        assert reconnected_events[0].exchange_name == "binance"
        assert "1 tentative" in reconnected_events[0].details

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff_delays(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Les delais d'attente suivent 2s, 4s, 8s, 16s, 30s (cap)."""
        attempt = 0

        async def fail_then_succeed(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt < 5:
                raise ccxt.NetworkError("still down")
            return mock_ccxt_exchange.markets

        mock_ccxt_exchange.load_markets = AsyncMock(side_effect=fail_then_succeed)
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with patch("src.exchange.ccxt_connector.asyncio.sleep", side_effect=mock_sleep):
            await connector._reconnect()

        assert sleep_calls[0] == pytest.approx(2.0)
        assert sleep_calls[1] == pytest.approx(4.0)
        assert sleep_calls[2] == pytest.approx(8.0)
        assert sleep_calls[3] == pytest.approx(16.0)
        assert sleep_calls[4] == pytest.approx(30.0)  # cap MAX_RECONNECT_DELAY

    @pytest.mark.asyncio
    async def test_reconnect_resets_attempts_on_success(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Apres reconnexion reussie, _reconnect_attempts revient a 0."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange
        connector._reconnect_attempts = 3

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            await connector._reconnect()

        assert connector._reconnect_attempts == 0
        assert connector._is_connected is True

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts_emits_critical_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Apres 5 echecs, ERROR_CRITICAL est emis."""
        mock_ccxt_exchange.load_markets = AsyncMock(
            side_effect=ccxt.NetworkError("still down")
        )

        critical_events = []

        async def handler(event):
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError, match="5 tentatives"):
                await connector._reconnect()

        assert len(critical_events) == 1
        assert critical_events[0].event_type == EventType.ERROR_CRITICAL
        assert "5 tentatives" in critical_events[0].message

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts_raises_exception(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Apres 5 echecs, ExchangeConnectionError est propagee."""
        mock_ccxt_exchange.load_markets = AsyncMock(
            side_effect=ccxt.NetworkError("still down")
        )

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError, match="binance"):
                await connector._reconnect()


class TestCcxtConnectorVerifyPositions:
    """Tests de la verification post-reconnexion."""

    @pytest.mark.asyncio
    async def test_verify_positions_no_positions(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Aucune position ouverte -> pas d'erreur."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])

        critical_events = []

        async def handler(event):
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        await connector._verify_positions_after_reconnect()

        assert len(critical_events) == 0

    @pytest.mark.asyncio
    async def test_verify_positions_with_sl(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Positions ouvertes avec SL correspondant au side -> pas d'erreur."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1, "notional": 4200.0},
        ])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "type": "stop_market", "side": "sell", "stopPrice": 41000},
        ])

        critical_events = []

        async def handler(event):
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        await connector._verify_positions_after_reconnect()

        assert len(critical_events) == 0

    @pytest.mark.asyncio
    async def test_verify_positions_missing_sl_emits_critical(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Position sans SL -> ERROR_CRITICAL emis."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1, "notional": 4200.0},
        ])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        critical_events = []

        async def handler(event):
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        await connector._verify_positions_after_reconnect()

        assert len(critical_events) == 1
        assert "SL" in critical_events[0].message or "stop" in critical_events[0].message.lower()


class TestCcxtConnectorFetchPositions:
    """Tests de fetch_positions()."""

    @pytest.mark.asyncio
    async def test_fetch_positions_returns_open_positions(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Retourne les positions ouvertes (contracts > 0)."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
            {"symbol": "BTC/USDT", "side": "short", "contracts": 0},
        ])

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        positions = await connector.fetch_positions()

        assert len(positions) == 1
        assert positions[0]["contracts"] == 0.1

    @pytest.mark.asyncio
    async def test_fetch_positions_handles_network_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.NetworkError -> ExchangeConnectionError."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(
            side_effect=ccxt.NetworkError("timeout")
        )

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(ExchangeConnectionError, match="fetch_positions"):
            await connector.fetch_positions()

    @pytest.mark.asyncio
    async def test_fetch_positions_handles_exchange_error(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.BaseError -> ExchangeError."""
        mock_ccxt_exchange.fetch_positions = AsyncMock(
            side_effect=ccxt.BaseError("exchange error")
        )

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with pytest.raises(ExchangeError, match="fetch_positions"):
            await connector.fetch_positions()


class TestCcxtConnectorReconnectLogging:
    """Tests du logging de reconnexion."""

    @pytest.mark.asyncio
    async def test_reconnection_logs_disconnection_with_timestamp(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Le log de deconnexion contient le nom de l'exchange."""
        call_count = 0
        log_messages = []

        def log_sink(message):
            log_messages.append(str(message))

        async def mock_watch_ohlcv(symbol, timeframe, since=None, limit=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ccxt.NetworkError("Connection lost")
            else:
                raise asyncio.CancelledError()

        mock_ccxt_exchange.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)
        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        from loguru import logger
        handler_id = logger.add(log_sink, format="{time} {level} {message}")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange
        connector._is_connected = True

        try:
            with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(asyncio.CancelledError):
                    await connector.watch_candles()
        finally:
            logger.remove(handler_id)

        disconnection_logs = [m for m in log_messages if "Deconnexion" in m or "deconnexion" in m.lower()]
        assert len(disconnection_logs) >= 1

    @pytest.mark.asyncio
    async def test_reconnection_logs_attempt_number_and_delay(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Le log de tentative contient le numero et le delai."""
        log_messages = []

        def log_sink(message):
            log_messages.append(str(message))

        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        from loguru import logger
        handler_id = logger.add(log_sink, format="{message}")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        try:
            with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
                await connector._reconnect()
        finally:
            logger.remove(handler_id)

        attempt_logs = [m for m in log_messages if "1/5" in m and "2.0" in m]
        assert len(attempt_logs) >= 1

    @pytest.mark.asyncio
    async def test_reconnection_logs_success(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """Le log de reconnexion reussie est present."""
        log_messages = []

        def log_sink(message):
            log_messages.append(str(message))

        mock_ccxt_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt_exchange.fetch_open_orders = AsyncMock(return_value=[])

        from loguru import logger
        handler_id = logger.add(log_sink, format="{message}")

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        try:
            with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
                await connector._reconnect()
        finally:
            logger.remove(handler_id)

        success_logs = [m for m in log_messages if "Reconnexion reussie" in m]
        assert len(success_logs) >= 1


class TestCcxtConnectorAuthReconnect:
    """Test de reconnexion avec erreur d'authentification."""

    @pytest.mark.asyncio
    async def test_reconnect_authentication_error_emits_critical(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        mock_ccxt_exchange,
        mock_ccxt_pro,
    ) -> None:
        """ccxt.AuthenticationError ne retente pas -> ERROR_CRITICAL immediatement."""
        mock_ccxt_exchange.load_markets = AsyncMock(
            side_effect=ccxt.AuthenticationError("invalid key")
        )

        critical_events = []

        async def handler(event):
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
        connector._exchange = mock_ccxt_exchange

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError, match="authentification"):
                await connector._reconnect()

        assert len(critical_events) == 1
        assert "authentification" in critical_events[0].message.lower() or "authentication" in critical_events[0].message.lower()

