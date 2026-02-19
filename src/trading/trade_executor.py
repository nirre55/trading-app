"""Exécuteur de trades avec gestion atomique des ordres SL/TP."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from loguru import logger

from src.core.event_bus import EventBus
from src.core.exceptions import OrderFailedError
from src.exchange.base import BaseExchangeConnector
from src.models.events import ErrorEvent, EventType, StrategyEvent, TradeEvent
from src.models.exchange import OrderInfo, OrderSide, OrderStatus, OrderType
from src.models.trade import TradeDirection, TradeRecord, TradeStatus

__all__ = ["TradeExecutor"]


class TradeExecutor:
    """Exécuteur de trades avec garantie SL obligatoire (NFR10)."""

    def __init__(
        self,
        connector: BaseExchangeConnector,
        event_bus: EventBus,
    ) -> None:
        self._connector = connector
        self._event_bus = event_bus
        self._handle_signal_long_bound = self._handle_signal_long
        self._handle_signal_short_bound = self._handle_signal_short
        self._event_bus.on(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short_bound)  # type: ignore[arg-type]
        logger.debug("TradeExecutor initialisé — abonné aux signaux LONG/SHORT")

    async def _handle_signal_long(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Gestionnaire signal long — sera complété en Stories 4.2 et 4.3."""
        logger.info(
            "Signal LONG reçu pour {} — intégration complète en Stories 4.2/4.3",
            event.pair,
        )

    async def _handle_signal_short(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Gestionnaire signal short — sera complété en Stories 4.2 et 4.3."""
        logger.info(
            "Signal SHORT reçu pour {} — intégration complète en Stories 4.2/4.3",
            event.pair,
        )

    async def execute_atomic_trade(
        self,
        pair: str,
        direction: TradeDirection,
        quantity: Decimal,
        sl_price: Decimal,
        capital_before: Decimal,
        leverage: int = 1,
    ) -> TradeRecord | None:
        """Exécute un trade de manière atomique : entrée + SL obligatoire (FR7).

        Séquence atomique :
        1. Placer l'ordre d'entrée (MARKET)
        2. Placer l'ordre SL
        3. Vérifier que le statut SL est actif (FR10)
        4. Si SL échoue à n'importe quelle étape → fermer position immédiatement

        Returns:
            TradeRecord avec status=OPEN si succès, None si la position a été fermée.

        Raises:
            ValueError: Si quantity <= 0 ou sl_price <= 0 (erreur de programmation).
        """
        if quantity <= 0:
            raise ValueError(f"quantity doit être > 0, reçu: {quantity}")
        if sl_price <= 0:
            raise ValueError(f"sl_price doit être > 0, reçu: {sl_price}")

        trade_id = str(uuid.uuid4())
        side = OrderSide.BUY if direction == TradeDirection.LONG else OrderSide.SELL
        close_side = OrderSide.SELL if direction == TradeDirection.LONG else OrderSide.BUY

        logger.info(
            "Début séquence atomique — trade_id={} pair={} direction={} qty={} sl={}",
            trade_id,
            pair,
            direction,
            quantity,
            sl_price,
        )

        entry_order: OrderInfo | None = None

        try:
            # Étape 1 : Placer l'ordre d'entrée (MARKET)
            entry_order = await self._connector.place_order(
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
            )
            if entry_order.status == OrderStatus.FAILED:
                raise OrderFailedError(
                    f"Ordre d'entrée FAILED: id={entry_order.id}",
                    context={"order_id": entry_order.id, "status": str(entry_order.status)},
                )
            real_entry_price = entry_order.price or sl_price
            logger.info(
                "Ordre d'entrée confirmé — id={} price={}",
                entry_order.id,
                real_entry_price,
            )

            # Étape 2 : Placer l'ordre SL
            sl_order = await self._connector.place_order(
                side=close_side,
                order_type=OrderType.STOP_LOSS,
                quantity=quantity,
                price=sl_price,
            )

            # Étape 3 : Vérifier existence SL sur l'exchange (FR10)
            if not self._verify_sl_status(sl_order):
                raise OrderFailedError(
                    f"SL non actif sur l'exchange — id={sl_order.id} status={sl_order.status}",
                    context={"sl_order_id": sl_order.id, "status": str(sl_order.status)},
                )
            logger.info("SL confirmé sur l'exchange — id={} price={}", sl_order.id, sl_price)

            # Succès : construire le TradeRecord
            record = TradeRecord(
                id=trade_id,
                pair=pair,
                direction=direction,
                entry_price=real_entry_price,
                stop_loss=sl_price,
                take_profit=Decimal(0),  # placeholder — sera défini en Story 4.2
                leverage=leverage,
                quantity=quantity,
                status=TradeStatus.OPEN,
                capital_before=capital_before,
            )

            # Émettre TRADE_OPENED
            await self._event_bus.emit(
                EventType.TRADE_OPENED,
                TradeEvent(
                    event_type=EventType.TRADE_OPENED,
                    trade_id=trade_id,
                    pair=pair,
                    details=f"entry={real_entry_price} sl={sl_price} qty={quantity}",
                ),
            )
            logger.info(
                "Trade ouvert avec succès — trade_id={} entry={} sl={}",
                trade_id,
                real_entry_price,
                sl_price,
            )
            return record

        except asyncio.CancelledError:
            raise  # Ne pas intercepter — requis pour graceful shutdown
        except Exception as exc:
            logger.exception(
                "Échec séquence atomique — trade_id={} pair={} erreur={}",
                trade_id,
                pair,
                exc,
            )
            await self._close_position_on_failure(
                trade_id=trade_id,
                pair=pair,
                exc=exc,
                close_side=close_side,
                quantity=quantity,
                entry_order=entry_order,
            )
            return None

    def _verify_sl_status(self, sl_order: OrderInfo) -> bool:
        """Vérifie que l'ordre SL n'est pas dans un état terminal d'échec (FR10).

        Note: Méthode SYNCHRONE — vérifie l'objet déjà retourné, pas d'appel réseau.
        """
        is_active = sl_order.status not in (OrderStatus.FAILED, OrderStatus.CANCELLED)
        logger.debug(
            "Vérification SL — id={} status={} actif={}",
            sl_order.id,
            sl_order.status,
            is_active,
        )
        return is_active

    async def stop(self) -> None:
        """Désabonne les handlers du bus pour graceful shutdown."""
        self._event_bus.off(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long_bound)  # type: ignore[arg-type]
        self._event_bus.off(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short_bound)  # type: ignore[arg-type]
        logger.debug("TradeExecutor arrêté — handlers retirés du bus")

    async def _close_position_on_failure(
        self,
        trade_id: str,
        pair: str,
        exc: Exception,
        close_side: OrderSide,
        quantity: Decimal,
        entry_order: OrderInfo | None,
    ) -> None:
        """Ferme la position en cas d'échec et émet les événements appropriés."""
        # Fermer la position seulement si l'entrée a réellement été exécutée (pas FAILED)
        if entry_order is not None and entry_order.status != OrderStatus.FAILED:
            try:
                await self._connector.place_order(
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                )
                logger.info("Position fermée suite à échec SL — trade_id={}", trade_id)
            except Exception as close_exc:
                logger.exception(
                    "CRITIQUE: Impossible de fermer position après échec SL — trade_id={} erreur={}",
                    trade_id,
                    close_exc,
                )
                await self._event_bus.emit(
                    EventType.ERROR_CRITICAL,
                    ErrorEvent(
                        event_type=EventType.ERROR_CRITICAL,
                        error_type=type(close_exc).__name__,
                        message=(
                            f"Position non protégée — trade_id={trade_id} pair={pair} "
                            f"impossible de fermer: {close_exc}"
                        ),
                    ),
                )

        # Émettre TRADE_FAILED dans tous les cas
        await self._event_bus.emit(
            EventType.TRADE_FAILED,
            TradeEvent(
                event_type=EventType.TRADE_FAILED,
                trade_id=trade_id,
                pair=pair,
                details=str(exc),
            ),
        )
