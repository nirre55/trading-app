"""Tests unitaires pour BaseStrategy, ExampleStrategy et StrategyRegistry."""

from decimal import Decimal

import pytest

from src.core.event_bus import EventBus
from src.core.exceptions import ConfigError, TradingAppError
from src.core.state_machine import StateMachine
from src.models.config import CapitalConfig, ConditionConfig, StrategyConfig
from src.models.events import BaseEvent, CandleEvent, EventType, StrategyEvent
from src.models.state import StrategyStateEnum
from src.strategies.base import BaseStrategy
from src.strategies.example_strategy import ExampleStrategy
from src.strategies.registry import StrategyRegistry


# ── Fixtures helpers ─────────────────────────────────────────────────────────


def make_candle(close: float = 50000.0) -> CandleEvent:
    """Crée un CandleEvent de test."""
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="1h",
        open=Decimal(str(close)),
        high=Decimal(str(close + 100)),
        low=Decimal(str(close - 100)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
    )


def make_config(
    conditions: list[dict] | None = None,
    timeout_candles: int = 5,
) -> StrategyConfig:
    """Crée une StrategyConfig de test."""
    if conditions is None:
        conditions = [{"type": "test", "params": {"always_true": True}}]
    return StrategyConfig(
        name="test_strategy",
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[
            ConditionConfig(
                type=c["type"],
                params=c["params"],
                max_gap_candles=c.get("max_gap_candles"),
            )
            for c in conditions
        ],
        timeout_candles=timeout_candles,
        capital=CapitalConfig(mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=2.0),
    )


def make_strategy(
    config: StrategyConfig | None = None,
) -> tuple[ExampleStrategy, StateMachine, EventBus]:
    """Crée une ExampleStrategy avec bus et state machine de test."""
    bus = EventBus()
    if config is None:
        config = make_config()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)
    return strategy, sm, bus


@pytest.fixture
def isolated_registry():
    """Sauvegarde et restaure le registre entre tests pour l'isolation."""
    original = dict(StrategyRegistry._registry)
    yield
    StrategyRegistry._registry.clear()
    StrategyRegistry._registry.update(original)


# ── 4.1 Tests de l'interface abstraite (2 tests) ─────────────────────────────


def test_base_strategy_is_abstract() -> None:
    """BaseStrategy ne peut pas être instanciée directement — lève TypeError."""
    with pytest.raises(TypeError):
        BaseStrategy(  # type: ignore[abstract]
            config=make_config(),
            state_machine=StateMachine(EventBus(), "test", "BTC/USDT"),
            event_bus=EventBus(),
        )


def test_example_strategy_implements_interface() -> None:
    """ExampleStrategy peut être instanciée sans erreur."""
    strategy, _, _ = make_strategy()
    assert isinstance(strategy, BaseStrategy)
    assert isinstance(strategy, ExampleStrategy)


# ── 4.2 Tests de on_candle — compteur et skip (3 tests) ──────────────────────


@pytest.mark.asyncio
async def test_on_candle_increments_counter() -> None:
    """Chaque appel à on_candle() → candle_count += 1."""
    strategy, _, _ = make_strategy(make_config(
        conditions=[{"type": "test", "params": {"always_true": False}}]
    ))
    candle = make_candle()

    assert strategy.candle_count == 0
    await strategy.on_candle(candle)
    assert strategy.candle_count == 1
    await strategy.on_candle(candle)
    assert strategy.candle_count == 2


@pytest.mark.asyncio
async def test_on_candle_skips_when_in_trade() -> None:
    """État IN_TRADE → on_candle() incrémente le compteur mais ne délègue pas à evaluate_conditions."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": True}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Atteindre SIGNAL_READY via deux candles
    await strategy.on_candle(candle)
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.SIGNAL_READY

    # Passer en IN_TRADE
    await sm.on_trade_opened("trade-001")
    assert sm.state == StrategyStateEnum.IN_TRADE

    count_before = strategy.candle_count
    await strategy.on_candle(candle)

    assert strategy.candle_count == count_before + 1
    assert sm.state == StrategyStateEnum.IN_TRADE


@pytest.mark.asyncio
async def test_on_candle_skips_when_signal_ready() -> None:
    """État SIGNAL_READY → on_candle() incrémente le compteur mais ne délègue pas à evaluate_conditions."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": True}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Atteindre SIGNAL_READY via deux candles
    await strategy.on_candle(candle)
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.SIGNAL_READY

    count_before = strategy.candle_count
    await strategy.on_candle(candle)

    assert strategy.candle_count == count_before + 1
    assert sm.state == StrategyStateEnum.SIGNAL_READY


# ── 4.3–4.7 Tests des conditions séquentielles (5 tests) ─────────────────────


@pytest.mark.asyncio
async def test_first_condition_met_transitions_to_watching() -> None:
    """Condition[0] satisfaite → state_machine.state == WATCHING."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": False}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    await strategy.on_candle(candle)

    assert sm.state == StrategyStateEnum.WATCHING
    assert sm.conditions_met == [0]
    assert strategy.last_condition_candle == 1


@pytest.mark.asyncio
async def test_second_condition_met_after_first() -> None:
    """Conditions[0] et [1] satisfaites → state == WATCHING (2 conditions_met)."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": False}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    await strategy.on_candle(candle)
    await strategy.on_candle(candle)

    assert sm.state == StrategyStateEnum.WATCHING
    assert sm.conditions_met == [0, 1]


@pytest.mark.asyncio
async def test_all_conditions_met_transitions_to_signal_ready() -> None:
    """Config 2 conditions, les 2 satisfaites → state == SIGNAL_READY."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": True}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    await strategy.on_candle(candle)
    await strategy.on_candle(candle)

    assert sm.state == StrategyStateEnum.SIGNAL_READY
    assert sm.conditions_met == [0, 1]


@pytest.mark.asyncio
async def test_unmet_condition_stays_idle() -> None:
    """Condition always_true: False → state reste IDLE."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": False}},
    ])
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    await strategy.on_candle(candle)
    await strategy.on_candle(candle)

    assert sm.state == StrategyStateEnum.IDLE
    assert sm.conditions_met == []


# ── 4.5–4.6 Tests du gap timeout (4 tests) ───────────────────────────────────


@pytest.mark.asyncio
async def test_gap_timeout_with_per_condition_max_gap() -> None:
    """max_gap_candles=2 sur condition[1], 3 bougies sans que condition[1] soit satisfaite → timeout → state IDLE."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 2},
        ],
        timeout_candles=100,  # Global timeout élevé pour ne pas interférer
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Candle 1 : condition[0] satisfaite → WATCHING, last_condition_candle=1
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 2 : gap=1 ≤ 2 → pas de timeout
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 3 : gap=2 ≤ 2 → pas de timeout
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 4 : gap=3 > 2 → timeout → IDLE
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.IDLE


@pytest.mark.asyncio
async def test_gap_timeout_uses_global_timeout_when_no_per_condition() -> None:
    """max_gap_candles=None sur condition[1], timeout_candles=3, 4 bougies → timeout."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}},  # max_gap_candles=None
        ],
        timeout_candles=3,
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Candle 1 : condition[0] satisfaite → WATCHING, last_condition_candle=1
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candles 2 et 3 : gap ≤ 3 → pas de timeout
    await strategy.on_candle(candle)
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 4 : gap=3 ≤ 3 → pas encore de timeout
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 5 : gap=4 > 3 → timeout → IDLE
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.IDLE


@pytest.mark.asyncio
async def test_no_timeout_within_gap() -> None:
    """max_gap_candles=5 sur condition[1], 4 bougies → pas de timeout, état WATCHING maintenu."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 5},
        ],
        timeout_candles=100,
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Candle 1 : condition[0] satisfaite → WATCHING
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candles 2-5 : gap=1,2,3,4 ≤ 5 → pas de timeout
    for _ in range(4):
        await strategy.on_candle(candle)
        assert sm.state == StrategyStateEnum.WATCHING


@pytest.mark.asyncio
async def test_timeout_emits_strategy_timeout_event() -> None:
    """Timeout → bus reçoit STRATEGY_TIMEOUT."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 1},
        ],
        timeout_candles=100,
    )
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)

    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_TIMEOUT, handler)
    candle = make_candle()

    # Candle 1 : condition[0] satisfaite → WATCHING
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 2 : gap=1 ≤ 1 → pas de timeout
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 3 : gap=2 > 1 → timeout → IDLE, STRATEGY_TIMEOUT émis
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.IDLE
    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_TIMEOUT


# ── 4.8 Tests du registre (3 tests) ──────────────────────────────────────────


def test_registry_register_and_get(isolated_registry: None) -> None:
    """register('test_strat', MyClass) → get('test_strat') retourne MyClass."""

    class _TempStrategy:
        pass

    StrategyRegistry.register("test_strat", _TempStrategy)  # type: ignore[arg-type]
    result = StrategyRegistry.get("test_strat")
    assert result is _TempStrategy


def test_registry_get_unknown_raises_config_error(isolated_registry: None) -> None:
    """get('inexistant') → lève ConfigError avec match='introuvable'."""
    with pytest.raises(ConfigError, match="introuvable"):
        StrategyRegistry.get("strategie_inexistante_xyz")


def test_registry_list_available(isolated_registry: None) -> None:
    """Après register → list_available() contient le nom enregistré."""

    class _AnotherStrategy:
        pass

    StrategyRegistry.register("another_strat", _AnotherStrategy)  # type: ignore[arg-type]
    available = StrategyRegistry.list_available()
    assert "another_strat" in available


# ── Tests d'événements bus (2 tests) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_condition_met_emits_strategy_condition_met() -> None:
    """Condition satisfaite → bus reçoit STRATEGY_CONDITION_MET."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": False}},
    ])
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)

    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_CONDITION_MET, handler)
    candle = make_candle()

    await strategy.on_candle(candle)

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_CONDITION_MET
    assert received[0].condition_index == 0


@pytest.mark.asyncio
async def test_all_conditions_met_emits_signal_long() -> None:
    """Toutes les conditions satisfaites → bus reçoit STRATEGY_SIGNAL_LONG."""
    config = make_config(conditions=[
        {"type": "test", "params": {"always_true": True}},
        {"type": "test", "params": {"always_true": True}},
    ])
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)

    received: list[BaseEvent] = []

    async def handler(event: BaseEvent) -> None:
        received.append(event)

    bus.on(EventType.STRATEGY_SIGNAL_LONG, handler)
    candle = make_candle()

    await strategy.on_candle(candle)
    await strategy.on_candle(candle)

    assert len(received) == 1
    assert isinstance(received[0], StrategyEvent)
    assert received[0].event_type == EventType.STRATEGY_SIGNAL_LONG


# ── Test bonus — reset après timeout (1 test) ─────────────────────────────────


@pytest.mark.asyncio
async def test_last_condition_candle_resets_after_timeout() -> None:
    """Après timeout, last_condition_candle == 0 et candle_count continue de croître normalement."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 1},
        ],
        timeout_candles=100,
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Candle 1 : condition[0] satisfaite
    await strategy.on_candle(candle)
    assert strategy.last_condition_candle == 1

    # Candle 2 : gap=1 ≤ 1 → pas de timeout
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.WATCHING

    # Candle 3 : gap=2 > 1 → timeout → last_condition_candle reset à 0
    await strategy.on_candle(candle)
    assert sm.state == StrategyStateEnum.IDLE
    assert strategy.last_condition_candle == 0
    assert strategy.candle_count == 3


# ── H1 : intégration abonnement bus (1 test) ─────────────────────────────────


@pytest.mark.asyncio
async def test_bus_subscription_integration() -> None:
    """bus.emit(CANDLE_CLOSED) → on_candle() déclenché via l'abonnement du __init__."""
    config = make_config(conditions=[{"type": "test", "params": {"always_true": False}}])
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)
    candle = make_candle()

    assert strategy.candle_count == 0
    await bus.emit(EventType.CANDLE_CLOSED, candle)
    assert strategy.candle_count == 1
    await bus.emit(EventType.CANDLE_CLOSED, candle)
    assert strategy.candle_count == 2


# ── H2 : méthode stop() / désabonnement (1 test) ─────────────────────────────


@pytest.mark.asyncio
async def test_stop_unsubscribes_from_bus() -> None:
    """stop() → les émissions CANDLE_CLOSED ultérieures n'incrémentent plus le compteur."""
    config = make_config(conditions=[{"type": "test", "params": {"always_true": False}}])
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)
    strategy = ExampleStrategy(config, sm, bus)
    candle = make_candle()

    await bus.emit(EventType.CANDLE_CLOSED, candle)
    assert strategy.candle_count == 1

    strategy.stop()

    await bus.emit(EventType.CANDLE_CLOSED, candle)
    assert strategy.candle_count == 1  # plus incrémenté après stop()


# ── L1 : get_signal() invalide → TradingAppError (1 test) ────────────────────


@pytest.mark.asyncio
async def test_invalid_get_signal_raises_trading_app_error() -> None:
    """get_signal() retournant une valeur invalide → TradingAppError via StateMachine."""
    config = make_config(conditions=[{"type": "test", "params": {"always_true": True}}])
    bus = EventBus()
    sm = StateMachine(bus, config.name, config.pair)

    class _BadSignalStrategy(BaseStrategy):
        async def evaluate_conditions(self, candle: CandleEvent) -> None:
            await self._state_machine.on_condition_met(0, self._candle_count)
            self._last_condition_candle = self._candle_count
            await self._state_machine.on_all_conditions_met(self.get_signal())

        def get_signal(self) -> str:
            return "DIRECTION_INVALIDE"

    strategy = _BadSignalStrategy(config, sm, bus)

    with pytest.raises(TradingAppError, match="Direction invalide"):
        await strategy.on_candle(make_candle())


# ── L2 : re-cycle complet après timeout (1 test) ─────────────────────────────


@pytest.mark.asyncio
async def test_recycle_after_timeout() -> None:
    """Après un timeout → IDLE, la stratégie redémarre un nouveau cycle correctement."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 1},
        ],
        timeout_candles=100,
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    # Cycle 1 : condition[0] satisfaite (candle 1), timeout (candle 3)
    await strategy.on_candle(candle)  # candle 1 → WATCHING
    await strategy.on_candle(candle)  # candle 2 : gap=1 ≤ 1, WATCHING
    await strategy.on_candle(candle)  # candle 3 : gap=2 > 1, timeout → IDLE
    assert sm.state == StrategyStateEnum.IDLE
    assert sm.conditions_met == []
    assert strategy.last_condition_candle == 0

    # Cycle 2 : depuis IDLE, condition[0] peut être re-satisfaite
    await strategy.on_candle(candle)  # candle 4 : condition[0] re-satisfaite
    assert sm.state == StrategyStateEnum.WATCHING
    assert sm.conditions_met == [0]
    assert strategy.last_condition_candle == 4


# ── L3 : timeout vérifie le reset de conditions_met (1 test) ─────────────────


@pytest.mark.asyncio
async def test_timeout_resets_conditions_met() -> None:
    """Timeout → conditions_met vidé par StateMachine._reset_conditions()."""
    config = make_config(
        conditions=[
            {"type": "test", "params": {"always_true": True}},
            {"type": "test", "params": {"always_true": False}, "max_gap_candles": 1},
        ],
        timeout_candles=100,
    )
    strategy, sm, _ = make_strategy(config)
    candle = make_candle()

    await strategy.on_candle(candle)
    assert sm.conditions_met == [0]  # condition[0] satisfaite

    await strategy.on_candle(candle)  # gap=1 ≤ 1, WATCHING
    await strategy.on_candle(candle)  # gap=2 > 1 → timeout
    assert sm.state == StrategyStateEnum.IDLE
    assert sm.conditions_met == []  # _reset_conditions() bien appelé
