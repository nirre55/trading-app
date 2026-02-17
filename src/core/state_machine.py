"""Machine à états générique pour la gestion des cycles de stratégie."""

from datetime import datetime, timezone

from loguru import logger

from src.core.event_bus import EventBus
from src.core.exceptions import TradingAppError
from src.models.events import EventType, StrategyEvent
from src.models.state import StrategyState, StrategyStateEnum

__all__ = ["StateMachine"]


class StateMachine:
    """Machine à états pour le cycle de vie d'une stratégie de trading."""

    def __init__(self, event_bus: EventBus, strategy_name: str, pair: str) -> None:
        self._bus = event_bus
        self._strategy_name = strategy_name
        self._pair = pair
        self._state: StrategyStateEnum = StrategyStateEnum.IDLE
        self._conditions_met: list[int] = []
        self._last_condition_candle: int | None = None
        self._current_trade_id: str | None = None
        self._last_transition_at: datetime = datetime.now(timezone.utc)
        logger.debug(
            "StateMachine initialisée pour '{}' ({}) — état: IDLE",
            strategy_name,
            pair,
        )

    @property
    def state(self) -> StrategyStateEnum:
        """État courant de la machine."""
        return self._state

    @property
    def conditions_met(self) -> list[int]:
        """Liste des indices de conditions satisfaites."""
        return list(self._conditions_met)

    def _validate_transition(
        self, method_name: str, allowed_states: tuple[StrategyStateEnum, ...]
    ) -> None:
        """Valide que la transition est possible depuis l'état courant."""
        if self._state not in allowed_states:
            msg = (
                f"Transition invalide : '{method_name}' appelé depuis l'état "
                f"'{self._state}' (autorisé depuis : {[s.value for s in allowed_states]})"
            )
            logger.error("StateMachine '{}' — {}", self._strategy_name, msg)
            raise TradingAppError(msg, context={"state": self._state, "method": method_name})

    def _reset_conditions(self) -> None:
        """Réinitialise le suivi des conditions."""
        self._conditions_met = []
        self._last_condition_candle = None
        self._current_trade_id = None

    async def on_condition_met(
        self, condition_index: int, candle_index: int | None = None
    ) -> None:
        """Condition satisfaite → IDLE ou WATCHING → WATCHING."""
        self._validate_transition(
            "on_condition_met",
            (StrategyStateEnum.IDLE, StrategyStateEnum.WATCHING),
        )
        if condition_index in self._conditions_met:
            logger.warning(
                "StateMachine '{}' : condition #{} déjà enregistrée — ignorée",
                self._strategy_name,
                condition_index,
            )
            return
        from_state = self._state
        self._state = StrategyStateEnum.WATCHING
        self._conditions_met.append(condition_index)
        if candle_index is not None:
            self._last_condition_candle = candle_index
        self._last_transition_at = datetime.now(timezone.utc)
        logger.info(
            "StateMachine '{}' : {} → WATCHING (condition #{}, candle #{})",
            self._strategy_name,
            from_state,
            condition_index,
            candle_index,
        )
        await self._bus.emit(
            EventType.STRATEGY_CONDITION_MET,
            StrategyEvent(
                event_type=EventType.STRATEGY_CONDITION_MET,
                strategy_name=self._strategy_name,
                pair=self._pair,
                condition_index=condition_index,
                details=f"condition_{condition_index}_met",
            ),
        )

    async def on_all_conditions_met(self, direction: str = "long") -> None:
        """Toutes les conditions satisfaites → WATCHING → SIGNAL_READY."""
        self._validate_transition(
            "on_all_conditions_met", (StrategyStateEnum.WATCHING,)
        )
        direction_lower = direction.lower()
        if direction_lower not in ("long", "short"):
            msg = f"Direction invalide : '{direction}' (autorisé : 'long' ou 'short')"
            logger.error("StateMachine '{}' — {}", self._strategy_name, msg)
            raise TradingAppError(msg, context={"direction": direction})
        self._state = StrategyStateEnum.SIGNAL_READY
        self._last_transition_at = datetime.now(timezone.utc)
        event_type = (
            EventType.STRATEGY_SIGNAL_LONG
            if direction_lower == "long"
            else EventType.STRATEGY_SIGNAL_SHORT
        )
        logger.info(
            "StateMachine '{}' : WATCHING → SIGNAL_READY (signal {})",
            self._strategy_name,
            direction,
        )
        await self._bus.emit(
            event_type,
            StrategyEvent(
                event_type=event_type,
                strategy_name=self._strategy_name,
                pair=self._pair,
                details=f"signal_{direction}",
            ),
        )

    async def on_trade_opened(self, trade_id: str) -> None:
        """Trade ouvert → SIGNAL_READY → IN_TRADE."""
        self._validate_transition(
            "on_trade_opened", (StrategyStateEnum.SIGNAL_READY,)
        )
        self._state = StrategyStateEnum.IN_TRADE
        self._current_trade_id = trade_id
        self._last_transition_at = datetime.now(timezone.utc)
        logger.info(
            "StateMachine '{}' : SIGNAL_READY → IN_TRADE (trade_id={})",
            self._strategy_name,
            trade_id,
        )

    async def on_trade_closed(self) -> None:
        """Trade fermé → IN_TRADE → IDLE."""
        self._validate_transition(
            "on_trade_closed", (StrategyStateEnum.IN_TRADE,)
        )
        trade_id = self._current_trade_id
        self._state = StrategyStateEnum.IDLE
        self._reset_conditions()
        self._last_transition_at = datetime.now(timezone.utc)
        logger.info(
            "StateMachine '{}' : IN_TRADE → IDLE (trade_id={} fermé)",
            self._strategy_name,
            trade_id,
        )

    async def on_timeout(self) -> None:
        """Timeout entre conditions → WATCHING → IDLE."""
        self._validate_transition(
            "on_timeout", (StrategyStateEnum.WATCHING,)
        )
        self._state = StrategyStateEnum.IDLE
        self._reset_conditions()
        self._last_transition_at = datetime.now(timezone.utc)
        logger.info(
            "StateMachine '{}' : WATCHING → IDLE (timeout)",
            self._strategy_name,
        )
        await self._bus.emit(
            EventType.STRATEGY_TIMEOUT,
            StrategyEvent(
                event_type=EventType.STRATEGY_TIMEOUT,
                strategy_name=self._strategy_name,
                pair=self._pair,
                details="timeout_entre_conditions",
            ),
        )

    def get_strategy_state(self) -> StrategyState:
        """Retourne l'état courant sous forme de StrategyState sérialisable."""
        return StrategyState(
            state=self._state,
            conditions_met=list(self._conditions_met),
            last_condition_candle=self._last_condition_candle,
            current_trade_id=self._current_trade_id,
            timestamp=self._last_transition_at,
        )
