"""Tests pour l'émission de EXCHANGE_DISCONNECTED_PROLONGED dans _reconnect() — Story 8.3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import ccxt
import pytest
from pydantic import SecretStr

from src.core.event_bus import EventBus
from src.core.exceptions import ExchangeConnectionError
from src.exchange.ccxt_connector import CcxtConnector
from src.models.config import ExchangeConfig
from src.models.events import BaseEvent, EventType


@pytest.fixture
def exchange_config() -> ExchangeConfig:
    return ExchangeConfig(
        name="binance",
        api_key=SecretStr("test_key"),
        api_secret=SecretStr("test_secret"),
        testnet=True,
    )


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def _make_connected_connector(
    exchange_config: ExchangeConfig,
    event_bus: EventBus,
    mock_exchange: AsyncMock,
) -> CcxtConnector:
    """Crée un connecteur pré-initialisé avec un mock exchange (simulant post-connect)."""
    connector = CcxtConnector(exchange_config, event_bus, "BTC/USDT", "1m")
    connector._exchange = mock_exchange
    connector._exchange_name = "binance"
    connector._is_connected = True
    return connector


# ── AC 3 : Émission de EXCHANGE_DISCONNECTED_PROLONGED après 60s ──────────────


class TestReconnectProlongedDisconnection:
    """AC3 : EXCHANGE_DISCONNECTED_PROLONGED émis quand la déconnexion dépasse 60s."""

    @pytest.mark.asyncio
    async def test_prolonged_event_emis_quand_delai_cumule_atteint_60s(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ):
        """Après 60s de délai cumulé (5 tentatives), EXCHANGE_DISCONNECTED_PROLONGED est émis."""
        mock_exchange = AsyncMock()
        # Toutes les tentatives échouent
        mock_exchange.load_markets.side_effect = ccxt.NetworkError("réseau indisponible")
        connector = _make_connected_connector(exchange_config, event_bus, mock_exchange)

        emitted_types: list[EventType] = []

        async def _record_event(event: BaseEvent) -> None:
            emitted_types.append(event.event_type)

        event_bus.on(EventType.EXCHANGE_DISCONNECTED_PROLONGED, _record_event)

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError):
                await connector._reconnect()

        assert EventType.EXCHANGE_DISCONNECTED_PROLONGED in emitted_types

    @pytest.mark.asyncio
    async def test_prolonged_event_emis_une_seule_fois(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ):
        """EXCHANGE_DISCONNECTED_PROLONGED est émis exactement une fois, même si plusieurs seuils dépassés."""
        mock_exchange = AsyncMock()
        mock_exchange.load_markets.side_effect = ccxt.NetworkError("réseau indisponible")
        connector = _make_connected_connector(exchange_config, event_bus, mock_exchange)

        emitted_count = {"count": 0}

        async def _count_event(event: BaseEvent) -> None:
            emitted_count["count"] += 1

        event_bus.on(EventType.EXCHANGE_DISCONNECTED_PROLONGED, _count_event)

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError):
                await connector._reconnect()

        assert emitted_count["count"] == 1

    @pytest.mark.asyncio
    async def test_prolonged_event_non_emis_si_reconnexion_rapide(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ):
        """Si la reconnexion réussit au 1er essai (< 60s cumulé), l'événement n'est PAS émis."""
        mock_exchange = AsyncMock()
        mock_exchange.load_markets.return_value = {}  # succès immédiat
        mock_exchange.fetch_positions = AsyncMock(return_value=[])
        mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
        connector = _make_connected_connector(exchange_config, event_bus, mock_exchange)
        connector._market_rules = MagicMock()

        emitted_prolonged = {"fired": False}

        async def _detect_prolonged(event: BaseEvent) -> None:
            emitted_prolonged["fired"] = True

        event_bus.on(EventType.EXCHANGE_DISCONNECTED_PROLONGED, _detect_prolonged)

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            await connector._reconnect()

        assert not emitted_prolonged["fired"]

    @pytest.mark.asyncio
    async def test_prolonged_event_exchange_name_correct(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
    ):
        """L'événement EXCHANGE_DISCONNECTED_PROLONGED contient le bon exchange_name."""
        from src.models.events import ExchangeEvent

        mock_exchange = AsyncMock()
        mock_exchange.load_markets.side_effect = ccxt.NetworkError("réseau indisponible")
        connector = _make_connected_connector(exchange_config, event_bus, mock_exchange)

        received_events: list[ExchangeEvent] = []

        async def _capture_event(event: BaseEvent) -> None:
            if isinstance(event, ExchangeEvent):
                received_events.append(event)

        event_bus.on(EventType.EXCHANGE_DISCONNECTED_PROLONGED, _capture_event)

        with patch("src.exchange.ccxt_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ExchangeConnectionError):
                await connector._reconnect()

        assert len(received_events) == 1
        assert received_events[0].exchange_name == "binance"
