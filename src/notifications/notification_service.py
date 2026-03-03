"""Service de notifications Telegram (optionnel, mode dégradé si indisponible)."""

from __future__ import annotations

import asyncio
import urllib.parse
import urllib.request

from loguru import logger

from src.models.config import TelegramConfig

__all__ = ["NotificationService"]

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _http_send(url: str) -> None:
    """Envoie une requête HTTP GET (exécutée dans un thread séparé)."""
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        resp.read()


class NotificationService:
    """Service de notifications Telegram.

    Si la config est absente ou désactivée, toutes les méthodes sont des no-ops.
    En cas d'erreur HTTP (token invalide, réseau), le service passe en mode dégradé :
    un WARN est loggé mais aucune exception n'est propagée (FR51).
    """

    def __init__(self, config: TelegramConfig | None) -> None:
        self._config = config

    def _is_active(self) -> bool:
        """Retourne True si Telegram est configuré et activé."""
        return self._config is not None and self._config.enabled

    async def send_message(self, text: str) -> None:
        """Envoie un message texte via Telegram Bot API.

        Si Telegram est désactivé ou en cas d'erreur, aucune exception n'est levée.
        """
        if self._config is None or not self._config.enabled:
            return

        token = self._config.token.get_secret_value()
        chat_id = self._config.chat_id
        encoded_text = urllib.parse.quote(text)
        base_url = _TELEGRAM_API_BASE.format(token=token)
        url = f"{base_url}?chat_id={urllib.parse.quote(chat_id)}&text={encoded_text}"

        try:
            await asyncio.to_thread(_http_send, url)
        except Exception as err:
            logger.warning("[WARN] Telegram non joignable : {}", err)

    async def send_startup_message(self) -> None:
        """Envoie le message de démarrage du système (AC5)."""
        await self.send_message("[OK] Système démarré")
