"""Tests pour NotificationService (Story 8.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.config import TelegramConfig
from src.notifications.notification_service import NotificationService


def _make_config(enabled: bool = True, token: str = "bot123:AAAA", chat_id: str = "999") -> TelegramConfig:
    return TelegramConfig(enabled=enabled, token=token, chat_id=chat_id)


class TestNotificationServiceInit:
    """Tests d'initialisation du NotificationService."""

    def test_init_avec_config_none(self):
        svc = NotificationService(None)
        assert svc._config is None

    def test_init_avec_config_disabled(self):
        config = _make_config(enabled=False)
        svc = NotificationService(config)
        assert svc._config is not None
        assert svc._config.enabled is False

    def test_init_avec_config_enabled(self):
        config = _make_config(enabled=True)
        svc = NotificationService(config)
        assert svc._config is not None
        assert svc._config.enabled is True


class TestSendMessageDisabled:
    """AC2 : NotificationService ne fait rien si Telegram est désactivé."""

    @pytest.mark.asyncio
    async def test_send_message_config_none_ne_fait_rien(self):
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            await svc.send_message("test")
            mock_to_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_disabled_ne_fait_rien(self):
        svc = NotificationService(_make_config(enabled=False))
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            await svc.send_message("test")
            mock_to_thread.assert_not_called()


class TestSendMessageEnabled:
    """AC5 : NotificationService envoie un message quand Telegram est activé."""

    @pytest.mark.asyncio
    async def test_send_startup_message_appelle_send_message(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts: list[str] = []

        async def fake_send(text: str) -> None:
            sent_texts.append(text)

        svc.send_message = fake_send  # type: ignore[method-assign]
        await svc.send_startup_message()
        assert len(sent_texts) == 1
        assert "[OK] Système démarré" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        svc = NotificationService(_make_config(enabled=True))
        with patch("src.notifications.notification_service.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = MagicMock()
            await svc.send_message("Bonjour")
            mock_to_thread.assert_called_once()


class TestSendMessageDegradedMode:
    """AC4 : mode dégradé — token invalide → WARN loggé, aucune exception."""

    @pytest.mark.asyncio
    async def test_http_error_log_warn_no_exception(self):
        svc = NotificationService(_make_config(enabled=True, token="invalid_token"))
        with (
            patch("src.notifications.notification_service.asyncio.to_thread", side_effect=Exception("HTTP 401")),
            patch("src.notifications.notification_service.logger") as mock_logger,
        ):
            await svc.send_message("test")  # Ne doit PAS lever d'exception
            mock_logger.warning.assert_called_once()
            warn_call = mock_logger.warning.call_args[0][0]
            assert "[WARN] Telegram non joignable" in warn_call

    @pytest.mark.asyncio
    async def test_degraded_mode_systeme_continue(self):
        svc = NotificationService(_make_config(enabled=True))
        with (
            patch("src.notifications.notification_service.asyncio.to_thread", side_effect=OSError("timeout")),
            patch("src.notifications.notification_service.logger"),
        ):
            # Ne doit pas propager l'exception
            await svc.send_message("test")


class TestTokenAbsentDesLogs:
    """AC3 : token absent des logs via register_sensitive_values."""

    def test_token_masque_par_sanitize_message(self):
        from src.core.logging import _sanitize_message, register_sensitive_values

        token = "1234567890:AAFakeTokenForTestingPurposesOnly000"
        register_sensitive_values(token)
        msg = f"Connexion Telegram avec token {token} active"
        sanitized = _sanitize_message(msg)
        assert token not in sanitized
        assert "***" in sanitized
