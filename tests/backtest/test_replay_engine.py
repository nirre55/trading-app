"""Tests pour le ReplayEngine — Story 5.2."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backtest.replay_engine import ReplayEngine
from src.core.event_bus import EventBus
from src.models.events import CandleEvent, EventType

START_DT = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DT = datetime(2024, 1, 10, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)

SAMPLE_CANDLES = [
    [START_MS + i * 3_600_000, 42000.0 + i, 43000.0 + i, 41000.0 + i, 42500.0 + i, 100.0 + i]
    for i in range(3)
]


@pytest.fixture
def mock_downloader() -> MagicMock:
    downloader = MagicMock()
    downloader.download = AsyncMock(return_value=SAMPLE_CANDLES)
    return downloader


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def engine(mock_downloader: MagicMock, event_bus: EventBus) -> ReplayEngine:
    return ReplayEngine(data_downloader=mock_downloader, event_bus=event_bus)


@pytest.mark.asyncio
async def test_run_emits_candle_closed_for_each_candle(
    engine: ReplayEngine, event_bus: EventBus
) -> None:
    """Vérifie que N bougies → N émissions CANDLE_CLOSED."""
    received: list[CandleEvent] = []

    async def handler(event: CandleEvent) -> None:
        received.append(event)

    event_bus.on(EventType.CANDLE_CLOSED, handler)  # type: ignore[arg-type]
    await engine.run("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert len(received) == len(SAMPLE_CANDLES)
    for event in received:
        assert event.event_type == EventType.CANDLE_CLOSED


@pytest.mark.asyncio
async def test_run_converts_float_to_decimal(
    engine: ReplayEngine, event_bus: EventBus
) -> None:
    """Vérifie que open/high/low/close/volume sont des Decimal."""
    received: list[CandleEvent] = []

    async def handler(event: CandleEvent) -> None:
        received.append(event)

    event_bus.on(EventType.CANDLE_CLOSED, handler)  # type: ignore[arg-type]
    await engine.run("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert len(received) > 0
    event = received[0]
    assert isinstance(event.open, Decimal)
    assert isinstance(event.high, Decimal)
    assert isinstance(event.low, Decimal)
    assert isinstance(event.close, Decimal)
    assert isinstance(event.volume, Decimal)
    # Vérification de la valeur exacte via str pour éviter erreurs flottantes
    assert event.open == Decimal(str(SAMPLE_CANDLES[0][1]))


@pytest.mark.asyncio
async def test_run_sets_correct_timestamp_from_ms(
    engine: ReplayEngine, event_bus: EventBus
) -> None:
    """Vérifie que timestamp_ms → datetime UTC correct."""
    received: list[CandleEvent] = []

    async def handler(event: CandleEvent) -> None:
        received.append(event)

    event_bus.on(EventType.CANDLE_CLOSED, handler)  # type: ignore[arg-type]
    await engine.run("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert len(received) > 0
    event = received[0]
    expected_dt = datetime.fromtimestamp(SAMPLE_CANDLES[0][0] / 1000, tz=timezone.utc)
    assert event.timestamp == expected_dt
    assert event.timestamp.tzinfo is not None  # UTC aware


@pytest.mark.asyncio
async def test_run_passes_pair_and_timeframe(
    engine: ReplayEngine, event_bus: EventBus
) -> None:
    """Vérifie que pair/timeframe sont correctement transmis dans chaque CandleEvent."""
    received: list[CandleEvent] = []

    async def handler(event: CandleEvent) -> None:
        received.append(event)

    event_bus.on(EventType.CANDLE_CLOSED, handler)  # type: ignore[arg-type]
    await engine.run("binance", "ETH/USDT", "4h", START_DT, END_DT)

    assert all(event.pair == "ETH/USDT" for event in received)
    assert all(event.timeframe == "4h" for event in received)


@pytest.mark.asyncio
async def test_run_empty_candles_no_emit(event_bus: EventBus) -> None:
    """Vérifie que 0 bougie → 0 émission sur le bus."""
    downloader = MagicMock()
    downloader.download = AsyncMock(return_value=[])
    engine = ReplayEngine(data_downloader=downloader, event_bus=event_bus)

    received: list[CandleEvent] = []

    async def handler(event: CandleEvent) -> None:
        received.append(event)

    event_bus.on(EventType.CANDLE_CLOSED, handler)  # type: ignore[arg-type]
    await engine.run("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert len(received) == 0


@pytest.mark.asyncio
async def test_run_calls_downloader_download(mock_downloader: MagicMock, event_bus: EventBus) -> None:
    """Vérifie que DataDownloader.download() est appelé avec les bons arguments."""
    engine = ReplayEngine(data_downloader=mock_downloader, event_bus=event_bus)
    await engine.run("kraken", "ETH/USDT", "15m", START_DT, END_DT)

    mock_downloader.download.assert_called_once_with("kraken", "ETH/USDT", "15m", START_DT, END_DT)
