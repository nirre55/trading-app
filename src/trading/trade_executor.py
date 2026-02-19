"""Exécuteur de trades avec gestion atomique des ordres SL/TP."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger

from src.capital.base import BaseCapitalManager
from src.core.event_bus import EventBus
from src.core.exceptions import OrderFailedError, TradeError
from src.exchange.base import BaseExchangeConnector
from src.exchange.order_validator import OrderValidator
from src.models.config import StrategyConfig
from src.models.events import ErrorEvent, EventType, StrategyEvent, TradeEvent
from src.models.exchange import OrderInfo, OrderSide, OrderStatus, OrderType
from src.models.trade import TradeDirection, TradeRecord, TradeResult, TradeStatus

__all__ = ["TradeExecutor"]


class TradeExecutor:
    """Exécuteur de trades avec garantie SL obligatoire (NFR10)."""

    def __init__(
        self,
        connector: BaseExchangeConnector,
        event_bus: EventBus,
        config: StrategyConfig,
        capital_manager: BaseCapitalManager,
    ) -> None:
        self._connector = connector
        self._event_bus = event_bus
        self._config = config
        self._capital_manager = capital_manager
        self._open_trades: dict[str, TradeRecord] = {}
        self._closed_trades: dict[str, TradeResult] = {}
        self._handle_signal_long_bound = self._handle_signal_long
        self._handle_signal_short_bound = self._handle_signal_short
        self._handle_sl_hit_bound = self._handle_trade_closed
        self._handle_tp_hit_bound = self._handle_trade_closed
        self._event_bus.on(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.TRADE_SL_HIT, self._handle_sl_hit_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.TRADE_TP_HIT, self._handle_tp_hit_bound)  # type: ignore[arg-type]
        logger.debug("TradeExecutor initialisé — abonné aux signaux LONG/SHORT et événements SL/TP")

    async def _handle_signal_long(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Gestionnaire signal LONG — calcul position sizing + exécution atomique (FR11, FR12, FR27)."""
        logger.info(
            "Signal LONG reçu — pair={} signal_price={} sl_price={}",
            event.pair,
            event.signal_price,
            event.sl_price,
        )
        if event.signal_price is None or event.sl_price is None:
            logger.warning(
                "Signal LONG ignoré — signal_price ou sl_price manquant — pair={}",
                event.pair,
            )
            return
        try:
            balance = await self._connector.fetch_balance()
            capital_before = balance.free
            quantity = self._capital_manager.calculate_position_size(
                balance=capital_before,
                entry_price=event.signal_price,
                stop_loss=event.sl_price,
            )
            record = await self.execute_atomic_trade(
                pair=event.pair,
                direction=TradeDirection.LONG,
                quantity=quantity,
                signal_price=event.signal_price,
                sl_price=event.sl_price,
                capital_before=capital_before,
            )
            if record is not None:
                self._open_trades[str(record.id)] = record
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Erreur traitement signal LONG — pair={} erreur={}", event.pair, exc
            )

    async def _handle_signal_short(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Gestionnaire signal SHORT — calcul position sizing + exécution atomique (FR11, FR12, FR27)."""
        logger.info(
            "Signal SHORT reçu — pair={} signal_price={} sl_price={}",
            event.pair,
            event.signal_price,
            event.sl_price,
        )
        if event.signal_price is None or event.sl_price is None:
            logger.warning(
                "Signal SHORT ignoré — signal_price ou sl_price manquant — pair={}",
                event.pair,
            )
            return
        try:
            balance = await self._connector.fetch_balance()
            capital_before = balance.free
            quantity = self._capital_manager.calculate_position_size(
                balance=capital_before,
                entry_price=event.signal_price,
                stop_loss=event.sl_price,
            )
            record = await self.execute_atomic_trade(
                pair=event.pair,
                direction=TradeDirection.SHORT,
                quantity=quantity,
                signal_price=event.signal_price,
                sl_price=event.sl_price,
                capital_before=capital_before,
            )
            if record is not None:
                self._open_trades[str(record.id)] = record
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Erreur traitement signal SHORT — pair={} erreur={}", event.pair, exc
            )

    async def _handle_trade_closed(self, event: TradeEvent) -> None:  # type: ignore[arg-type]
        """Gère la clôture d'un trade (SL ou TP touché) — calcul P&L (FR28, FR29)."""
        trade_id = event.trade_id
        trade_record = self._open_trades.pop(trade_id, None)
        if trade_record is None:
            logger.warning("Trade clôturé inconnu — trade_id={}", trade_id)
            return
        try:
            balance_after = await self._connector.fetch_balance()
            capital_after = balance_after.free
            pnl = capital_after - trade_record.capital_before
            duration = datetime.now(timezone.utc) - trade_record.timestamp

            if event.exit_price is not None:
                exit_price = event.exit_price
            elif event.event_type == EventType.TRADE_SL_HIT:
                exit_price = trade_record.stop_loss
            else:
                exit_price = trade_record.take_profit

            result = TradeResult(
                trade_id=str(trade_record.id),
                pair=trade_record.pair,
                direction=trade_record.direction,
                entry_price=trade_record.entry_price,
                exit_price=exit_price,
                stop_loss=trade_record.stop_loss,
                take_profit=trade_record.take_profit,
                leverage=trade_record.leverage,
                pnl=pnl,
                duration=duration,
                capital_before=trade_record.capital_before,
                capital_after=capital_after,
            )

            self._closed_trades[trade_id] = result

            await self._event_bus.emit(
                EventType.TRADE_CLOSED,
                TradeEvent(
                    event_type=EventType.TRADE_CLOSED,
                    trade_id=trade_id,
                    pair=trade_record.pair,
                    exit_price=exit_price,
                    pnl=pnl,
                    capital_before=trade_record.capital_before,
                    capital_after=capital_after,
                    details=(
                        f"capital_before={trade_record.capital_before} "
                        f"capital_after={capital_after} pnl={pnl}"
                    ),
                ),
            )
            logger.info(
                "Trade clôturé — trade_id={} pnl={} capital_before={} capital_after={}",
                trade_id,
                pnl,
                trade_record.capital_before,
                capital_after,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Erreur calcul P&L — trade_id={} erreur={}", trade_id, exc
            )

    def _calculate_tp_sl(
        self,
        direction: TradeDirection,
        real_entry_price: Decimal,
        signal_price: Decimal,
        signal_sl_price: Decimal,
        risk_reward_ratio: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Calcule TP et SL recalculés sur le prix réel d'entrée (FR8, FR9).

        Args:
            direction: Direction du trade (LONG/SHORT)
            real_entry_price: Prix réel d'exécution de l'entrée (depuis entry_order.price)
            signal_price: Prix du signal (avant exécution) — sert à calculer sl_distance
            signal_sl_price: Prix SL absolu du signal (avant recalcul)
            risk_reward_ratio: Ratio risk/reward (ex: 2.0 = TP = 2× la distance SL)

        Returns:
            (real_tp_price, real_sl_price) bruts avant arrondi tick_size

        Raises:
            ValueError: si sl_distance == 0 (signal_price == signal_sl_price — invalide)
        """
        sl_distance = abs(signal_price - signal_sl_price)
        if sl_distance == 0:
            raise ValueError(
                f"Distance SL invalide : signal_price ({signal_price}) == sl_price ({signal_sl_price})"
            )
        if direction == TradeDirection.LONG:
            real_sl = real_entry_price - sl_distance
            real_tp = real_entry_price + sl_distance * risk_reward_ratio
        else:  # SHORT
            real_sl = real_entry_price + sl_distance
            real_tp = real_entry_price - sl_distance * risk_reward_ratio
        return real_tp, real_sl

    async def execute_atomic_trade(
        self,
        pair: str,
        direction: TradeDirection,
        quantity: Decimal,
        signal_price: Decimal,
        sl_price: Decimal,
        capital_before: Decimal,
    ) -> TradeRecord | None:
        """Exécute un trade de manière atomique : levier → entrée → SL → TP (FR7, FR8, FR9, FR10, FR13, FR14).

        Séquence atomique :
        1. Valider inputs (quantity, sl_price, signal_price > 0 ; pair == connector.pair)
        2. Charger market_rules → calculer effective_leverage → set_leverage()
        3. Placer l'ordre d'entrée (MARKET)
        4. Recalculer TP/SL sur prix réel → arrondir tick_size
        5. Placer l'ordre SL → vérifier statut SL (FR10)
        6. Placer l'ordre TP (échec TP = warning, pas fermeture — position protégée par SL)
        7. Retourner TradeRecord avec valeurs réelles

        Returns:
            TradeRecord avec status=OPEN si succès, None si la position a été fermée.

        Raises:
            ValueError: Si inputs invalides ou pair ne correspond pas à connector.pair [M3]
            TradeError: Si market_rules non chargées
        """
        if quantity <= 0:
            raise ValueError(f"quantity doit être > 0, reçu: {quantity}")
        if sl_price <= 0:
            raise ValueError(f"sl_price doit être > 0, reçu: {sl_price}")
        if signal_price <= 0:
            raise ValueError(f"signal_price doit être > 0, reçu: {signal_price}")
        if pair != self._connector.pair:  # [M3]
            raise ValueError(
                f"pair '{pair}' ne correspond pas à la paire du connecteur '{self._connector.pair}'"
            )

        market_rules = self._connector.market_rules
        if market_rules is None:
            raise TradeError(
                "market_rules non chargées — appelez connector.fetch_market_rules() avant execute_atomic_trade()"
            )

        trade_id = str(uuid.uuid4())
        side = OrderSide.BUY if direction == TradeDirection.LONG else OrderSide.SELL
        close_side = OrderSide.SELL if direction == TradeDirection.LONG else OrderSide.BUY

        effective_leverage = min(self._config.leverage, market_rules.max_leverage)

        logger.info(
            "Début séquence atomique — trade_id={} pair={} direction={} qty={} sl={} levier={}",
            trade_id,
            pair,
            direction,
            quantity,
            sl_price,
            effective_leverage,
        )

        entry_order: OrderInfo | None = None

        try:
            # Étape 1 : Appliquer le levier avant l'ordre d'entrée (FR14)
            await self._connector.set_leverage(pair, effective_leverage)
            logger.debug("Levier {} appliqué pour {}", effective_leverage, pair)

            # Étape 2 : Placer l'ordre d'entrée (MARKET)
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
            if entry_order.price is None:
                logger.warning(
                    "Prix d'entrée absent sur l'ordre — utilisation du signal_price={} — trade_id={}",
                    signal_price,
                    trade_id,
                )
                real_entry_price = signal_price
            else:
                real_entry_price = entry_order.price
            logger.info(
                "Ordre d'entrée confirmé — id={} price={}",
                entry_order.id,
                real_entry_price,
            )

            # Étape 3 : Recalculer TP/SL sur prix réel + arrondi tick_size (FR8, FR9, FR13)
            validator = OrderValidator(market_rules)
            rr = Decimal(str(self._config.capital.risk_reward_ratio))
            raw_tp, raw_sl = self._calculate_tp_sl(
                direction, real_entry_price, signal_price, sl_price, rr
            )
            real_tp_price = validator.round_price(raw_tp)
            real_sl_price = validator.round_price(raw_sl)
            logger.info(
                "TP/SL recalculés — entry_réel={} tp={} sl={} (signal_price={} signal_sl={})",
                real_entry_price,
                real_tp_price,
                real_sl_price,
                signal_price,
                sl_price,
            )

            # Étape 4 : Placer l'ordre SL (prix recalculé sur entrée réelle)
            sl_order = await self._connector.place_order(
                side=close_side,
                order_type=OrderType.STOP_LOSS,
                quantity=quantity,
                price=real_sl_price,
            )

            # Étape 5 : Vérifier existence SL sur l'exchange (FR10)
            if not self._verify_sl_status(sl_order):
                raise OrderFailedError(
                    f"SL non actif sur l'exchange — id={sl_order.id} status={sl_order.status}",
                    context={"sl_order_id": sl_order.id, "status": str(sl_order.status)},
                )
            logger.info("SL confirmé sur l'exchange — id={} price={}", sl_order.id, real_sl_price)

            # Étape 6 : Placer l'ordre TP (échec TP = warning seulement, position protégée par SL)
            try:
                tp_order = await self._connector.place_order(
                    side=close_side,
                    order_type=OrderType.TAKE_PROFIT,
                    quantity=quantity,
                    price=real_tp_price,
                )
                logger.info("TP placé sur l'exchange — id={} price={}", tp_order.id, real_tp_price)
            except Exception as tp_exc:
                logger.warning(
                    "TP non placé (position protégée par SL) — trade_id={} erreur={}",
                    trade_id,
                    tp_exc,
                )

            # Succès : construire le TradeRecord avec les valeurs réelles
            record = TradeRecord(
                id=trade_id,
                pair=pair,
                direction=direction,
                entry_price=real_entry_price,
                stop_loss=real_sl_price,
                take_profit=real_tp_price,
                leverage=effective_leverage,
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
                    details=f"entry={real_entry_price} sl={real_sl_price} tp={real_tp_price} leverage={effective_leverage}",
                ),
            )
            logger.info(
                "Trade ouvert avec succès — trade_id={} entry={} sl={} tp={}",
                trade_id,
                real_entry_price,
                real_sl_price,
                real_tp_price,
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
        self._event_bus.off(EventType.TRADE_SL_HIT, self._handle_sl_hit_bound)  # type: ignore[arg-type]
        self._event_bus.off(EventType.TRADE_TP_HIT, self._handle_tp_hit_bound)  # type: ignore[arg-type]
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
