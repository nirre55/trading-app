"""Tests unitaires de la StateMachine (Story 3.1)."""

import json

import pytest

from src.core.event_bus import EventBus
from src.core.exceptions import TradingAppError
from src.core.state_machine import StateMachine
from src.models.events import BaseEvent, EventType, StrategyEvent
from src.models.state import StrategyState, StrategyStateEnum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_machine(strategy_name: str = "test_strategy", pair: str = "BTC/USDT") -> tuple[StateMachine, EventBus]:
    """Crée une StateMachine avec un EventBus réel pour les tests."""
    bus = EventBus()
    machine = StateMachine(bus, strategy_name, pair)
    return machine, bus


# ---------------------------------------------------------------------------
# 2.1 Tests de création et état initial (1 test)
# ---------------------------------------------------------------------------


def test_state_machine_initial_state() -> None:
    """StateMachine créée → state == IDLE, conditions_met == [], get_strategy_state().state == IDLE."""
    machine, _ = make_machine()

    assert machine.state == StrategyStateEnum.IDLE
    assert machine.conditions_met == []
    state = machine.get_strategy_state()
    assert state.state == StrategyStateEnum.IDLE
    assert state.conditions_met == []
    assert state.current_trade_id is None
    assert state.last_condition_candle is None


# ---------------------------------------------------------------------------
# 2.2 Tests des transitions valides (6 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_to_watching_on_condition_met() -> None:
    """IDLE → on_condition_met(0) → state == WATCHING, conditions_met == [0]."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)

    assert machine.state == StrategyStateEnum.WATCHING
    assert machine.conditions_met == [0]


@pytest.mark.asyncio
async def test_watching_to_watching_on_condition_met() -> None:
    """WATCHING → on_condition_met(1) → state == WATCHING, conditions_met == [0, 1]."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_condition_met(1)

    assert machine.state == StrategyStateEnum.WATCHING
    assert machine.conditions_met == [0, 1]


@pytest.mark.asyncio
async def test_watching_to_signal_ready_long() -> None:
    """on_all_conditions_met('long') → state == SIGNAL_READY."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("long")

    assert machine.state == StrategyStateEnum.SIGNAL_READY
    assert machine.conditions_met == [0]


@pytest.mark.asyncio
async def test_watching_to_signal_ready_short() -> None:
    """on_all_conditions_met('short') → state == SIGNAL_READY."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("short")

    assert machine.state == StrategyStateEnum.SIGNAL_READY
    assert machine.conditions_met == [0]


@pytest.mark.asyncio
async def test_signal_ready_to_in_trade() -> None:
    """on_trade_opened('trade-123') → state == IN_TRADE, current_trade_id == 'trade-123'."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("long")
    await machine.on_trade_opened("trade-123")

    assert machine.state == StrategyStateEnum.IN_TRADE
    assert machine.get_strategy_state().current_trade_id == "trade-123"


@pytest.mark.asyncio
async def test_in_trade_to_idle_on_close() -> None:
    """on_trade_closed() → state == IDLE, conditions_met == [], current_trade_id == None."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("long")
    await machine.on_trade_opened("trade-123")
    await machine.on_trade_closed()

    assert machine.state == StrategyStateEnum.IDLE
    assert machine.conditions_met == []
    assert machine.get_strategy_state().current_trade_id is None


# ---------------------------------------------------------------------------
# 2.3 Tests des transitions invalides (5 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_on_all_conditions_met_raises() -> None:
    """IDLE → on_all_conditions_met() → raises TradingAppError, match='Transition invalide'."""
    machine, _ = make_machine()

    with pytest.raises(TradingAppError, match="Transition invalide"):
        await machine.on_all_conditions_met()


@pytest.mark.asyncio
async def test_idle_on_trade_opened_raises() -> None:
    """IDLE → on_trade_opened('t1') → raises TradingAppError."""
    machine, _ = make_machine()

    with pytest.raises(TradingAppError, match="Transition invalide"):
        await machine.on_trade_opened("t1")


@pytest.mark.asyncio
async def test_idle_on_timeout_raises() -> None:
    """IDLE → on_timeout() → raises TradingAppError."""
    machine, _ = make_machine()

    with pytest.raises(TradingAppError, match="Transition invalide"):
        await machine.on_timeout()


@pytest.mark.asyncio
async def test_watching_on_trade_opened_raises() -> None:
    """WATCHING → on_trade_opened('t1') → raises TradingAppError."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)

    with pytest.raises(TradingAppError, match="Transition invalide"):
        await machine.on_trade_opened("t1")


@pytest.mark.asyncio
async def test_in_trade_on_condition_met_raises() -> None:
    """IN_TRADE → on_condition_met(0) → raises TradingAppError."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("long")
    await machine.on_trade_opened("trade-abc")

    with pytest.raises(TradingAppError, match="Transition invalide"):
        await machine.on_condition_met(0)


# ---------------------------------------------------------------------------
# 2.4 Tests des événements émis sur le bus (4 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_met_emits_strategy_condition_met() -> None:
    """on_condition_met(0) → bus reçoit STRATEGY_CONDITION_MET avec strategy_name correct."""
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_CONDITION_MET, handler)
    machine = StateMachine(bus, "test_strategy", "BTC/USDT")
    await machine.on_condition_met(0, candle_index=42)

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_CONDITION_MET
    assert received[0].strategy_name == "test_strategy"
    assert received[0].condition_index == 0


@pytest.mark.asyncio
async def test_all_conditions_met_long_emits_signal_long() -> None:
    """on_all_conditions_met('long') → bus reçoit STRATEGY_SIGNAL_LONG."""
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_LONG, handler)
    machine = StateMachine(bus, "test_strategy", "BTC/USDT")
    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("long")

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_SIGNAL_LONG


@pytest.mark.asyncio
async def test_all_conditions_met_short_emits_signal_short() -> None:
    """on_all_conditions_met('short') → bus reçoit STRATEGY_SIGNAL_SHORT."""
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_SHORT, handler)
    machine = StateMachine(bus, "test_strategy", "BTC/USDT")
    await machine.on_condition_met(0)
    await machine.on_all_conditions_met("short")

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_SIGNAL_SHORT


@pytest.mark.asyncio
async def test_timeout_emits_strategy_timeout() -> None:
    """on_timeout() → bus reçoit STRATEGY_TIMEOUT."""
    bus = EventBus()
    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_TIMEOUT, handler)
    machine = StateMachine(bus, "test_strategy", "BTC/USDT")
    await machine.on_condition_met(0)
    await machine.on_timeout()

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_TIMEOUT


# ---------------------------------------------------------------------------
# 2.5 Tests de sérialisation get_strategy_state() (3 tests)
# ---------------------------------------------------------------------------


def test_get_strategy_state_returns_strategy_state() -> None:
    """get_strategy_state() retourne une instance de StrategyState."""
    machine, _ = make_machine()

    result = machine.get_strategy_state()

    assert isinstance(result, StrategyState)


@pytest.mark.asyncio
async def test_get_strategy_state_conditions_met() -> None:
    """Après on_condition_met(2), get_strategy_state().conditions_met == [2]."""
    machine, _ = make_machine()

    await machine.on_condition_met(2)

    assert machine.get_strategy_state().conditions_met == [2]


@pytest.mark.asyncio
async def test_get_strategy_state_json_serializable() -> None:
    """get_strategy_state().model_dump_json() produit un JSON valide avec les champs attendus."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)

    json_str = machine.get_strategy_state().model_dump_json()
    data = json.loads(json_str)
    assert data["state"] == "WATCHING"
    assert data["conditions_met"] == [0]
    assert "timestamp" in data
    assert data["current_trade_id"] is None


# ---------------------------------------------------------------------------
# Test bonus : guard complet reset conditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_trade_closed_resets_conditions() -> None:
    """Cycle complet → state == IDLE, conditions_met == [], current_trade_id == None."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_condition_met(1)
    await machine.on_all_conditions_met("long")
    await machine.on_trade_opened("trade-xyz")
    await machine.on_trade_closed()

    state = machine.get_strategy_state()
    assert machine.state == StrategyStateEnum.IDLE
    assert machine.conditions_met == []
    assert state.current_trade_id is None
    assert state.last_condition_candle is None


# ---------------------------------------------------------------------------
# Tests des corrections code review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_conditions_met_invalid_direction_raises() -> None:
    """on_all_conditions_met('invalid') → raises TradingAppError (H1)."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)

    with pytest.raises(TradingAppError, match="Direction invalide"):
        await machine.on_all_conditions_met("invalid")


@pytest.mark.asyncio
async def test_last_condition_candle_not_overwritten_by_none() -> None:
    """on_condition_met(candle=42) puis on_condition_met() sans candle → last_condition_candle reste 42 (M1)."""
    machine, _ = make_machine()

    await machine.on_condition_met(0, candle_index=42)
    await machine.on_condition_met(1)  # sans candle_index

    assert machine.get_strategy_state().last_condition_candle == 42


@pytest.mark.asyncio
async def test_get_strategy_state_last_condition_candle() -> None:
    """on_condition_met(0, candle_index=42) → get_strategy_state().last_condition_candle == 42 (M5)."""
    machine, _ = make_machine()

    await machine.on_condition_met(0, candle_index=42)

    assert machine.get_strategy_state().last_condition_candle == 42


@pytest.mark.asyncio
async def test_condition_met_duplicate_ignored() -> None:
    """on_condition_met(0) deux fois → conditions_met == [0], pas de doublon (M6)."""
    machine, _ = make_machine()

    await machine.on_condition_met(0)
    await machine.on_condition_met(0)  # doublon — doit être ignoré

    assert machine.conditions_met == [0]
    assert machine.state == StrategyStateEnum.WATCHING
