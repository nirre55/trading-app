"""Tests pour le bus d'événements async."""

import asyncio
from decimal import Decimal

import pytest

from src.core.event_bus import EventBus
from src.models.events import (
    BaseEvent,
    CandleEvent,
    ErrorEvent,
    EventType,
    TradeEvent,
)


@pytest.mark.asyncio
async def test_on_and_emit_basic():
    """Enregistrer un handler, émettre un événement, vérifier appel avec bon payload."""
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.CANDLE_CLOSED, handler)

    candle = CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal("50000"),
        high=Decimal("51000"),
        low=Decimal("49000"),
        close=Decimal("50500"),
        volume=Decimal("100"),
    )

    await bus.emit(EventType.CANDLE_CLOSED, candle)

    assert len(received) == 1
    assert received[0] is candle


@pytest.mark.asyncio
async def test_emit_multiple_handlers():
    """Plusieurs handlers pour le même type, tous appelés dans l'ordre d'enregistrement."""
    bus = EventBus()
    order: list[int] = []

    async def handler1(event: BaseEvent) -> None:
        order.append(1)

    async def handler2(event: BaseEvent) -> None:
        order.append(2)

    bus.on(EventType.TRADE_OPENED, handler1)
    bus.on(EventType.TRADE_OPENED, handler2)

    event = TradeEvent(
        event_type=EventType.TRADE_OPENED,
        trade_id="T001",
        pair="BTC/USDT",
    )

    await bus.emit(EventType.TRADE_OPENED, event)

    assert order == [1, 2]


@pytest.mark.asyncio
async def test_handler_not_called_for_different_type():
    """Handler pour type A n'est PAS appelé quand type B est émis."""
    bus = EventBus()
    called = False

    async def handler(event: BaseEvent) -> None:
        nonlocal called
        called = True

    bus.on(EventType.APP_STARTED, handler)

    candle = CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal("50000"),
        high=Decimal("51000"),
        low=Decimal("49000"),
        close=Decimal("50500"),
        volume=Decimal("100"),
    )

    await bus.emit(EventType.CANDLE_CLOSED, candle)

    assert not called


@pytest.mark.asyncio
async def test_async_handler_awaited():
    """Les handlers async def sont correctement awaitables."""
    bus = EventBus()
    executed = False

    async def handler(event: BaseEvent) -> None:
        nonlocal executed
        await asyncio.sleep(0)
        executed = True

    bus.on(EventType.APP_STARTED, handler)

    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)

    assert executed


@pytest.mark.asyncio
async def test_error_in_handler_emits_error_event():
    """Handler qui raise ValueError -> événement error.recoverable émis."""
    bus = EventBus()
    error_events: list[BaseEvent] = []

    async def failing_handler(event: BaseEvent) -> None:
        raise ValueError("test error")

    async def error_spy(event: BaseEvent) -> None:
        error_events.append(event)

    bus.on(EventType.APP_STARTED, failing_handler)
    bus.on(EventType.ERROR_RECOVERABLE, error_spy)

    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)

    assert len(error_events) == 1
    assert isinstance(error_events[0], ErrorEvent)
    assert error_events[0].error_type == "ValueError"
    assert error_events[0].message == "test error"
    assert error_events[0].traceback is not None


@pytest.mark.asyncio
async def test_error_in_handler_continues_remaining():
    """Handler 1 raise, Handler 2 est quand même appelé."""
    bus = EventBus()
    handler2_called = False

    async def failing_handler(event: BaseEvent) -> None:
        raise RuntimeError("fail")

    async def handler2(event: BaseEvent) -> None:
        nonlocal handler2_called
        handler2_called = True

    bus.on(EventType.APP_STARTED, failing_handler)
    bus.on(EventType.APP_STARTED, handler2)

    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)

    assert handler2_called


@pytest.mark.asyncio
async def test_error_handler_no_infinite_recursion():
    """Handler d'erreur qui raise -> pas de boucle infinie, juste un log."""
    bus = EventBus()
    error_handler_call_count = 0

    async def failing_handler(event: BaseEvent) -> None:
        raise ValueError("trigger")

    async def failing_error_handler(event: BaseEvent) -> None:
        nonlocal error_handler_call_count
        error_handler_call_count += 1
        raise RuntimeError("error in error handler")

    bus.on(EventType.APP_STARTED, failing_handler)
    bus.on(EventType.ERROR_RECOVERABLE, failing_error_handler)

    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)

    assert error_handler_call_count == 1, "Le handler d'erreur doit être appelé exactement 1 fois"
    assert not bus._emitting_error, "Le flag anti-récursion doit être réinitialisé"


@pytest.mark.asyncio
async def test_off_unsubscribe():
    """Après off(), le handler n'est plus appelé."""
    bus = EventBus()
    count = 0

    async def handler(event: BaseEvent) -> None:
        nonlocal count
        count += 1

    bus.on(EventType.APP_STARTED, handler)

    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)
    assert count == 1

    bus.off(EventType.APP_STARTED, handler)
    await bus.emit(EventType.APP_STARTED, event)
    assert count == 1


@pytest.mark.asyncio
async def test_emit_no_handlers():
    """Émettre un événement sans handler enregistré -> aucune erreur."""
    bus = EventBus()
    event = BaseEvent(event_type=EventType.APP_STARTED)
    await bus.emit(EventType.APP_STARTED, event)


@pytest.mark.asyncio
async def test_has_handlers():
    """has_handlers() retourne True avec handlers, False sans."""
    bus = EventBus()

    async def handler(event: BaseEvent) -> None:
        pass

    assert not bus.has_handlers(EventType.APP_STARTED)

    bus.on(EventType.APP_STARTED, handler)
    assert bus.has_handlers(EventType.APP_STARTED)

    assert not bus.has_handlers(EventType.CANDLE_CLOSED)


@pytest.mark.asyncio
async def test_clear():
    """Après clear(), aucun handler n'est enregistré."""
    bus = EventBus()

    async def handler(event: BaseEvent) -> None:
        pass

    bus.on(EventType.APP_STARTED, handler)
    bus.on(EventType.CANDLE_CLOSED, handler)

    assert bus.has_handlers(EventType.APP_STARTED)
    assert bus.has_handlers(EventType.CANDLE_CLOSED)

    bus.clear()

    assert not bus.has_handlers(EventType.APP_STARTED)
    assert not bus.has_handlers(EventType.CANDLE_CLOSED)
