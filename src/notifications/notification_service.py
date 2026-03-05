"""Service de notifications Telegram (optionnel, mode dégradé si indisponible)."""

from __future__ import annotations

import asyncio
import urllib.parse
import urllib.request

from loguru import logger

from src.models.config import TelegramConfig
from src.models.events import ErrorEvent, TradeEvent

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

    def __init__(self, config: TelegramConfig | None, dry_run: bool = False) -> None:
        self._config = config
        self._dry_run = dry_run

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

    async def notify_trade_opened(self, event: TradeEvent) -> None:
        """Envoie une notification d'ouverture de trade (AC1, AC3, Story 8.2)."""
        prefix = "[DRY-RUN] " if self._dry_run else ""
        direction = event.direction or "?"
        entry = event.entry_price or "?"
        sl = event.stop_loss or "?"
        tp = event.take_profit or "?"
        qty = event.quantity or "?"
        text = (
            f"{prefix}Trade ouvert — {event.pair} {direction} | "
            f"Entrée: {entry} | SL: {sl} | TP: {tp} | Taille: {qty}"
        )
        await self.send_message(text)

    async def notify_critical_error(self, event: ErrorEvent) -> None:
        """Envoie une alerte Telegram en cas d'erreur critique (AC1, Story 8.3)."""
        message = event.message[:200] if len(event.message) > 200 else event.message
        await self.send_message(f"[CRITICAL] {event.error_type} — {message}")

    async def notify_recovery(self) -> None:
        """Envoie une notification de recovery après crash (AC2, Story 8.3)."""
        await self.send_message(
            "[RECOVERY] Système redémarré — vérification des positions en cours"
        )

    async def notify_prolonged_disconnection(self) -> None:
        """Envoie une alerte de déconnexion prolongée (AC3, Story 8.3)."""
        await self.send_message("[WARN] Déconnexion prolongée de l'exchange")

    async def notify_shutdown(self) -> None:
        """Envoie une notification d'arrêt propre du système (AC4, Story 8.3)."""
        await self.send_message("[OK] Système arrêté proprement")

    async def notify_trade_closed(self, event: TradeEvent) -> None:
        """Envoie une notification de fermeture de trade (AC2, AC3, Story 8.2)."""
        prefix = "[DRY-RUN] " if self._dry_run else ""
        pnl = event.pnl or 0
        pnl_str = f"{float(pnl):+.2f}"
        if event.capital_before and event.capital_before != 0:
            pnl_pct = float(pnl) / float(event.capital_before) * 100
            pnl_pct_str = f"{pnl_pct:+.2f}%"
        else:
            pnl_pct_str = "N/A"
        duration_str = _format_duration(event.duration_seconds)
        text = (
            f"{prefix}Trade fermé — {event.pair} | "
            f"P&L: {pnl_str} USDT ({pnl_pct_str}) | Durée: {duration_str}"
        )
        await self.send_message(text)


def _format_duration(seconds: float | None) -> str:
    """Formate une durée en secondes sous forme lisible (Xh Xm Xs)."""
    if seconds is None:
        return "N/A"
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    parts = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)
