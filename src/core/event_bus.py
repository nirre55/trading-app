"""Bus d'événements async custom pour la communication inter-modules."""

import inspect
import traceback as tb_module
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from src.models.events import BaseEvent, ErrorEvent, EventType

__all__ = ["EventBus", "AsyncHandler"]

AsyncHandler = Callable[[BaseEvent], Coroutine[Any, Any, None]]


class EventBus:
    """Bus d'événements async pub/sub pour la communication inter-modules."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[AsyncHandler]] = defaultdict(list)
        self._emitting_error: bool = False

    def on(self, event_type: EventType, handler: AsyncHandler) -> None:
        """Enregistre un handler pour un type d'événement."""
        if not inspect.iscoroutinefunction(handler):
            raise TypeError(f"Le handler doit être async, reçu {type(handler)}")
        self._handlers[event_type].append(handler)
        logger.debug("Handler enregistré pour {}", event_type)

    async def emit(self, event_type: EventType, payload: BaseEvent) -> None:
        """Émet un événement séquentiellement à tous les handlers enregistrés."""
        handlers = list(self._handlers.get(event_type, []))
        logger.debug("Émission {} à {} handler(s)", event_type, len(handlers))
        for handler in handlers:
            try:
                await handler(payload)
            except Exception as exc:
                logger.exception("Erreur dans handler pour {}: {}", event_type, exc)
                if self._emitting_error:
                    continue
                self._emitting_error = True
                try:
                    error_event = ErrorEvent(
                        event_type=EventType.ERROR_RECOVERABLE,
                        error_type=type(exc).__name__,
                        message=str(exc),
                        traceback=tb_module.format_exc(),
                    )
                    await self.emit(EventType.ERROR_RECOVERABLE, error_event)
                finally:
                    self._emitting_error = False

    def off(self, event_type: EventType, handler: AsyncHandler) -> None:
        """Retire un handler de la liste pour ce type."""
        if event_type in self._handlers:
            before = len(self._handlers[event_type])
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h is not handler
            ]
            if len(self._handlers[event_type]) < before:
                logger.debug("Handler retiré pour {}", event_type)
            else:
                logger.debug("Handler non trouvé pour {}", event_type)

    def has_handlers(self, event_type: EventType) -> bool:
        """Vérifie s'il y a des handlers enregistrés pour ce type."""
        return bool(self._handlers.get(event_type))

    def clear(self) -> None:
        """Supprime tous les handlers."""
        self._handlers.clear()
        logger.debug("Tous les handlers supprimés")
