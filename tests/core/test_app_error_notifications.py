"""Tests d'intégration pour _register_notification_subscriptions dans app.py — Story 8.3.

Ces tests utilisent directement TradingApp._register_notification_subscriptions() pour
vérifier que le code de app.py abonne correctement le NotificationService au bus d'événements.
Si on supprime ou modifie les event_bus.on() dans app.py, ces tests échouent.
"""

from __future__ import annotations

import pytest

from pydantic import SecretStr

from src.core.app import TradingApp
from src.core.event_bus import EventBus
from src.models.config import TelegramConfig
from src.models.events import AppEvent, BaseEvent, ErrorEvent, EventType, ExchangeEvent
from src.notifications.notification_service import NotificationService


def _make_notification_service(enabled: bool = True) -> NotificationService:
    config = TelegramConfig(enabled=enabled, token=SecretStr("bot123:AAA"), chat_id="999")
    return NotificationService(config)


def _setup_app_subscriptions() -> tuple[EventBus, NotificationService]:
    """Configure TradingApp et enregistre les abonnements via _register_notification_subscriptions."""
    app = TradingApp()
    bus = EventBus()
    ns = _make_notification_service()
    app.event_bus = bus
    app._register_notification_subscriptions(ns)
    return bus, ns


# ── AC 1 : Abonnement error.critical ──────────────────────────────────────────


class TestErrorCriticalSubscription:
    """AC1 : notify_critical_error est appelé par _register_notification_subscriptions via ERROR_CRITICAL."""

    @pytest.mark.asyncio
    async def test_error_critical_declenche_notification(self):
        """Émettre ERROR_CRITICAL sur le bus appelle notify_critical_error (via app.py)."""
        bus, ns = _setup_app_subscriptions()
        called_with: list[ErrorEvent] = []

        async def _spy(event: ErrorEvent) -> None:
            called_with.append(event)

        ns.notify_critical_error = _spy  # type: ignore[method-assign]

        error_event = ErrorEvent(
            event_type=EventType.ERROR_CRITICAL,
            error_type="MissingStopLoss",
            message="SL absent",
        )
        await bus.emit(EventType.ERROR_CRITICAL, error_event)

        assert len(called_with) == 1
        assert called_with[0].error_type == "MissingStopLoss"

    @pytest.mark.asyncio
    async def test_error_critical_sans_errorevent_ignoree(self):
        """Un BaseEvent (non ErrorEvent) sur ERROR_CRITICAL est filtré par isinstance."""
        bus, ns = _setup_app_subscriptions()
        called = {"count": 0}

        async def _spy(event: ErrorEvent) -> None:
            called["count"] += 1

        ns.notify_critical_error = _spy  # type: ignore[method-assign]

        base_event = BaseEvent(event_type=EventType.ERROR_CRITICAL)
        await bus.emit(EventType.ERROR_CRITICAL, base_event)

        assert called["count"] == 0


# ── AC 2 : Abonnement app.recovery ────────────────────────────────────────────


class TestAppRecoverySubscription:
    """AC2 : notify_recovery est appelé par _register_notification_subscriptions via APP_RECOVERY."""

    @pytest.mark.asyncio
    async def test_app_recovery_declenche_notification(self):
        """Émettre APP_RECOVERY sur le bus appelle notify_recovery (via app.py)."""
        bus, ns = _setup_app_subscriptions()
        called = {"count": 0}

        async def _spy() -> None:
            called["count"] += 1

        ns.notify_recovery = _spy  # type: ignore[method-assign]

        recovery_event = AppEvent(event_type=EventType.APP_RECOVERY)
        await bus.emit(EventType.APP_RECOVERY, recovery_event)

        assert called["count"] == 1

    @pytest.mark.asyncio
    async def test_app_recovery_event_valide(self):
        """APP_RECOVERY est un AppEvent valide (event_type commence par 'app.')."""
        event = AppEvent(event_type=EventType.APP_RECOVERY)
        assert event.event_type == EventType.APP_RECOVERY
        assert event.event_type.value.startswith("app.")


# ── AC 3 : Abonnement exchange.disconnected_prolonged ─────────────────────────


class TestProlongedDisconnectionSubscription:
    """AC3 : notify_prolonged_disconnection est appelé via _register_notification_subscriptions."""

    @pytest.mark.asyncio
    async def test_prolonged_disconnection_declenche_notification(self):
        """Émettre EXCHANGE_DISCONNECTED_PROLONGED appelle notify_prolonged_disconnection (via app.py)."""
        bus, ns = _setup_app_subscriptions()
        called = {"count": 0}

        async def _spy() -> None:
            called["count"] += 1

        ns.notify_prolonged_disconnection = _spy  # type: ignore[method-assign]

        prolonged_event = ExchangeEvent(
            event_type=EventType.EXCHANGE_DISCONNECTED_PROLONGED,
            exchange_name="binance",
        )
        await bus.emit(EventType.EXCHANGE_DISCONNECTED_PROLONGED, prolonged_event)

        assert called["count"] == 1

    @pytest.mark.asyncio
    async def test_prolonged_event_valide(self):
        """EXCHANGE_DISCONNECTED_PROLONGED est un ExchangeEvent valide."""
        event = ExchangeEvent(
            event_type=EventType.EXCHANGE_DISCONNECTED_PROLONGED,
            exchange_name="binance",
        )
        assert event.event_type == EventType.EXCHANGE_DISCONNECTED_PROLONGED
        assert event.event_type.value.startswith("exchange.")


# ── AC 4 : Abonnement app.stopped ─────────────────────────────────────────────


class TestAppStoppedSubscription:
    """AC4 : notify_shutdown est appelé par _register_notification_subscriptions via APP_STOPPED."""

    @pytest.mark.asyncio
    async def test_app_stopped_declenche_notification(self):
        """Émettre APP_STOPPED sur le bus appelle notify_shutdown (via app.py)."""
        bus, ns = _setup_app_subscriptions()
        called = {"count": 0}

        async def _spy() -> None:
            called["count"] += 1

        ns.notify_shutdown = _spy  # type: ignore[method-assign]

        stopped_event = AppEvent(event_type=EventType.APP_STOPPED)
        await bus.emit(EventType.APP_STOPPED, stopped_event)

        assert called["count"] == 1
