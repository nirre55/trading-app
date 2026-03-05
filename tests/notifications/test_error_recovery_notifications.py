"""Tests pour les notifications erreurs critiques et recovery — Story 8.3."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.models.config import TelegramConfig
from src.models.events import ErrorEvent, EventType
from src.notifications.notification_service import NotificationService


def _make_config(enabled: bool = True, token: str = "bot123:AAAA", chat_id: str = "999") -> TelegramConfig:
    return TelegramConfig(enabled=enabled, token=token, chat_id=chat_id)


def _capture_send(svc: NotificationService) -> list[str]:
    """Intercepte send_message et retourne les textes capturés."""
    captured: list[str] = []

    async def fake_send(text: str) -> None:
        captured.append(text)

    svc.send_message = fake_send  # type: ignore[method-assign]
    return captured


def _make_error_event(
    error_type: str = "MissingStopLoss",
    message: str = "SL manquant sur la position BTC/USDT",
) -> ErrorEvent:
    return ErrorEvent(
        event_type=EventType.ERROR_CRITICAL,
        error_type=error_type,
        message=message,
    )


# ── AC 1 : Notification erreur critique ───────────────────────────────────────


class TestNotifyCriticalError:
    """AC1 : notification Telegram en cas d'erreur critique."""

    @pytest.mark.asyncio
    async def test_notify_critical_error_envoie_message(self):
        """notify_critical_error envoie un message via send_message."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_critical_error(_make_error_event())
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_notify_critical_error_contient_critical(self):
        """Le message contient le tag [CRITICAL]."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_critical_error(_make_error_event())
        assert "[CRITICAL]" in sent[0]

    @pytest.mark.asyncio
    async def test_notify_critical_error_contient_error_type(self):
        """Le message contient le error_type."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_critical_error(_make_error_event(error_type="InsufficientBalance"))
        assert "InsufficientBalance" in sent[0]

    @pytest.mark.asyncio
    async def test_notify_critical_error_contient_message(self):
        """Le message contient le contenu de l'erreur."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_critical_error(
            _make_error_event(message="Balance insuffisante : 5 USDT < 10 requis")
        )
        assert "Balance insuffisante" in sent[0]

    @pytest.mark.asyncio
    async def test_notify_critical_error_config_none_ne_fait_rien(self):
        """Config None : aucun appel réseau."""
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_thread:
            await svc.notify_critical_error(_make_error_event())
            mock_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_critical_error_disabled_ne_fait_rien(self):
        """Config disabled : aucun appel réseau."""
        svc = NotificationService(_make_config(enabled=False))
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_thread:
            await svc.notify_critical_error(_make_error_event())
            mock_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_critical_error_tronque_message_superieur_200_chars(self):
        """Un message > 200 chars est tronqué à exactement 200 chars dans la notification."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        long_message = "X" * 250
        await svc.notify_critical_error(_make_error_event(message=long_message))
        assert len(sent) == 1
        assert "X" * 200 in sent[0]
        assert "X" * 201 not in sent[0]

    @pytest.mark.asyncio
    async def test_notify_critical_error_message_exactement_200_chars_non_tronque(self):
        """Un message de exactement 200 chars n'est pas tronqué."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        exact_message = "Y" * 200
        await svc.notify_critical_error(_make_error_event(message=exact_message))
        assert len(sent) == 1
        assert "Y" * 200 in sent[0]


# ── AC 5 : Échec Telegram ne bloque pas la gestion d'erreur ───────────────────


class TestNotifyCriticalErrorModeDegrage:
    """AC5 : Telegram indisponible → loggé, aucune exception propagée."""

    @pytest.mark.asyncio
    async def test_notify_critical_error_mode_degrade_pas_exception(self):
        """L'échec Telegram n'empêche pas la gestion de l'erreur principale."""
        svc = NotificationService(_make_config(enabled=True))
        with (
            patch(
                "src.notifications.notification_service.asyncio.to_thread",
                side_effect=OSError("timeout"),
            ),
            patch("src.notifications.notification_service.logger"),
        ):
            # Ne doit PAS lever d'exception
            await svc.notify_critical_error(_make_error_event())

    @pytest.mark.asyncio
    async def test_notify_critical_error_mode_degrade_logge_warn(self):
        """L'échec Telegram est loggé en WARN."""
        svc = NotificationService(_make_config(enabled=True))
        with (
            patch(
                "src.notifications.notification_service.asyncio.to_thread",
                side_effect=Exception("HTTP 500"),
            ),
            patch("src.notifications.notification_service.logger") as mock_logger,
        ):
            await svc.notify_critical_error(_make_error_event())
            mock_logger.warning.assert_called_once()


# ── AC 2 : Notification recovery ──────────────────────────────────────────────


class TestNotifyRecovery:
    """AC2 : notification de recovery après crash."""

    @pytest.mark.asyncio
    async def test_notify_recovery_envoie_message(self):
        """notify_recovery envoie un message via send_message."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_recovery()
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_notify_recovery_message_fixe(self):
        """Le message contient exactement le texte défini dans l'AC2."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_recovery()
        assert "[RECOVERY]" in sent[0]
        assert "redémarré" in sent[0]
        assert "vérification des positions" in sent[0]

    @pytest.mark.asyncio
    async def test_notify_recovery_config_none_ne_fait_rien(self):
        """Config None : aucun appel réseau."""
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_thread:
            await svc.notify_recovery()
            mock_thread.assert_not_called()


# ── AC 3 : Notification déconnexion prolongée ─────────────────────────────────


class TestNotifyProlongedDisconnection:
    """AC3 : notification de déconnexion prolongée."""

    @pytest.mark.asyncio
    async def test_notify_prolonged_disconnection_envoie_message(self):
        """notify_prolonged_disconnection envoie un message via send_message."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_prolonged_disconnection()
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_notify_prolonged_disconnection_message_contient_warn(self):
        """Le message contient [WARN] et 'déconnexion prolongée'."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_prolonged_disconnection()
        assert "[WARN]" in sent[0]
        assert "prolongée" in sent[0].lower() or "prolongee" in sent[0].lower()

    @pytest.mark.asyncio
    async def test_notify_prolonged_disconnection_config_none_ne_fait_rien(self):
        """Config None : aucun appel réseau."""
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_thread:
            await svc.notify_prolonged_disconnection()
            mock_thread.assert_not_called()


# ── AC 4 : Notification arrêt propre ──────────────────────────────────────────


class TestNotifyShutdown:
    """AC4 : notification d'arrêt propre du système."""

    @pytest.mark.asyncio
    async def test_notify_shutdown_envoie_message(self):
        """notify_shutdown envoie un message via send_message."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_shutdown()
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_notify_shutdown_message_ok(self):
        """Le message contient [OK] et 'arrêté proprement'."""
        svc = NotificationService(_make_config(enabled=True))
        sent = _capture_send(svc)
        await svc.notify_shutdown()
        assert "[OK]" in sent[0]
        assert "proprement" in sent[0]

    @pytest.mark.asyncio
    async def test_notify_shutdown_config_none_ne_fait_rien(self):
        """Config None : aucun appel réseau."""
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_thread:
            await svc.notify_shutdown()
            mock_thread.assert_not_called()
