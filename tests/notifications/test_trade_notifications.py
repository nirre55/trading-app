"""Tests pour les notifications de trades — Story 8.2."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from src.models.config import TelegramConfig
from src.models.events import EventType, TradeEvent
from src.notifications.notification_service import NotificationService


def _make_config(enabled: bool = True, token: str = "bot123:AAAA", chat_id: str = "999") -> TelegramConfig:
    return TelegramConfig(enabled=enabled, token=token, chat_id=chat_id)


def _make_trade_opened_event(
    pair: str = "BTC/USDT",
    direction: str = "LONG",
    entry_price: str = "50000",
    stop_loss: str = "49000",
    take_profit: str = "52000",
    quantity: str = "0.01",
) -> TradeEvent:
    return TradeEvent(
        event_type=EventType.TRADE_OPENED,
        trade_id="trade-001",
        pair=pair,
        direction=direction,
        entry_price=Decimal(entry_price),
        stop_loss=Decimal(stop_loss),
        take_profit=Decimal(take_profit),
        quantity=Decimal(quantity),
    )


def _make_trade_closed_event(
    pair: str = "BTC/USDT",
    pnl: str = "25.50",
    capital_before: str = "1000.00",
    duration_seconds: float = 3720.0,
) -> TradeEvent:
    return TradeEvent(
        event_type=EventType.TRADE_CLOSED,
        trade_id="trade-001",
        pair=pair,
        pnl=Decimal(pnl),
        capital_before=Decimal(capital_before),
        duration_seconds=duration_seconds,
    )


def _capture_send(svc: NotificationService) -> list[str]:
    """Intercepte send_message et retourne les textes capturés."""
    captured: list[str] = []

    async def fake_send(text: str) -> None:
        captured.append(text)

    svc.send_message = fake_send  # type: ignore[method-assign]
    return captured


# ── AC 1 : Notification ouverture ─────────────────────────────────────────────


class TestNotifyTradeOpened:
    """AC1 : message ouverture avec paire, direction, entry, SL, TP, quantité."""

    @pytest.mark.asyncio
    async def test_notify_trade_opened_envoie_message(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(_make_trade_opened_event())
        assert len(sent_texts) == 1

    @pytest.mark.asyncio
    async def test_notify_trade_opened_contient_pair(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(_make_trade_opened_event(pair="ETH/USDT"))
        assert "ETH/USDT" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_notify_trade_opened_contient_direction(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(_make_trade_opened_event(direction="SHORT"))
        assert "SHORT" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_notify_trade_opened_contient_prix(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(
            _make_trade_opened_event(
                entry_price="50000",
                stop_loss="49000",
                take_profit="52000",
                quantity="0.01",
            )
        )
        msg = sent_texts[0]
        assert "50000" in msg  # entry
        assert "49000" in msg  # SL
        assert "52000" in msg  # TP
        assert "0.01" in msg   # quantity


# ── AC 2 : Notification fermeture ─────────────────────────────────────────────


class TestNotifyTradeClosed:
    """AC2 : message fermeture avec paire, P&L USDT, P&L %, durée."""

    @pytest.mark.asyncio
    async def test_notify_trade_closed_envoie_message(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_closed(_make_trade_closed_event())
        assert len(sent_texts) == 1

    @pytest.mark.asyncio
    async def test_notify_trade_closed_contient_pair(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_closed(_make_trade_closed_event(pair="ETH/USDT"))
        assert "ETH/USDT" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_notify_trade_closed_contient_pnl_usdt(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        await svc.notify_trade_closed(_make_trade_closed_event(pnl="25.50"))
        assert "25.50" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_notify_trade_closed_contient_pnl_pourcentage(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        # pnl=25.50, capital_before=1000.00 → 2.55%
        await svc.notify_trade_closed(_make_trade_closed_event(pnl="25.50", capital_before="1000.00"))
        assert "2.55" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_notify_trade_closed_contient_duree(self):
        svc = NotificationService(_make_config(enabled=True))
        sent_texts = _capture_send(svc)
        # 3720 secondes = 1h 2m 0s
        await svc.notify_trade_closed(_make_trade_closed_event(duration_seconds=3720.0))
        msg = sent_texts[0]
        assert "1h" in msg
        assert "2m" in msg


# ── AC 3 : Préfixe DRY-RUN ────────────────────────────────────────────────────


class TestDryRunPrefix:
    """AC3 : préfixe [DRY-RUN] sur les messages si dry_run=True."""

    @pytest.mark.asyncio
    async def test_dry_run_prefixe_ouverture(self):
        svc = NotificationService(_make_config(enabled=True), dry_run=True)
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(_make_trade_opened_event())
        assert "[DRY-RUN]" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_dry_run_prefixe_fermeture(self):
        svc = NotificationService(_make_config(enabled=True), dry_run=True)
        sent_texts = _capture_send(svc)
        await svc.notify_trade_closed(_make_trade_closed_event())
        assert "[DRY-RUN]" in sent_texts[0]

    @pytest.mark.asyncio
    async def test_pas_dry_run_sans_prefixe(self):
        svc = NotificationService(_make_config(enabled=True), dry_run=False)
        sent_texts = _capture_send(svc)
        await svc.notify_trade_opened(_make_trade_opened_event())
        assert "[DRY-RUN]" not in sent_texts[0]


# ── AC 4 : Mode dégradé ───────────────────────────────────────────────────────


class TestNotifyDegradedMode:
    """AC4 : send_message échoue → WARN loggé, aucune exception propagée."""

    @pytest.mark.asyncio
    async def test_notify_trade_opened_mode_degrade(self):
        svc = NotificationService(_make_config(enabled=True))
        with (
            patch("src.notifications.notification_service.asyncio.to_thread", side_effect=Exception("HTTP error")),
            patch("src.notifications.notification_service.logger") as mock_logger,
        ):
            event = _make_trade_opened_event()
            await svc.notify_trade_opened(event)  # Ne doit PAS lever d'exception
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_trade_closed_mode_degrade(self):
        svc = NotificationService(_make_config(enabled=True))
        with (
            patch("src.notifications.notification_service.asyncio.to_thread", side_effect=OSError("timeout")),
            patch("src.notifications.notification_service.logger") as mock_logger,
        ):
            event = _make_trade_closed_event()
            await svc.notify_trade_closed(event)  # Ne doit PAS lever d'exception
            mock_logger.warning.assert_called_once()


# ── AC 5 : Zéro appel réseau si désactivé ─────────────────────────────────────


class TestNotifyDisabled:
    """AC5 : enabled=False ou config=None → aucun appel réseau pour notify_trade_opened/closed."""

    @pytest.mark.asyncio
    async def test_notify_trade_opened_disabled_pas_appel_reseau(self):
        svc = NotificationService(_make_config(enabled=False))
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            event = _make_trade_opened_event()
            await svc.notify_trade_opened(event)
            mock_to_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_trade_closed_disabled_pas_appel_reseau(self):
        svc = NotificationService(_make_config(enabled=False))
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            event = _make_trade_closed_event()
            await svc.notify_trade_closed(event)
            mock_to_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_trade_opened_config_none_pas_appel_reseau(self):
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            event = _make_trade_opened_event()
            await svc.notify_trade_opened(event)
            mock_to_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_trade_closed_config_none_pas_appel_reseau(self):
        svc = NotificationService(None)
        with patch("src.notifications.notification_service.asyncio.to_thread") as mock_to_thread:
            event = _make_trade_closed_event()
            await svc.notify_trade_closed(event)
            mock_to_thread.assert_not_called()
