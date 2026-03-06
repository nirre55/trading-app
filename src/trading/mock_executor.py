"""Exécuteur simulé pour le mode dry-run — aucun ordre envoyé à l'exchange (Story 9.1)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger

from src.capital.base import BaseCapitalManager
from src.core.event_bus import EventBus
from src.exchange.base import BaseExchangeConnector
from src.models.config import StrategyConfig
from src.models.events import CandleEvent, EventType, StrategyEvent, TradeEvent
from src.models.trade import TradeDirection, TradeResult, TradeStatus
from src.trading.trade_logger import TradeLogger

__all__ = ["MockExecutor"]


class _SimulatedTrade:
    """Données d'un trade simulé en mémoire."""

    __slots__ = (
        "trade_id",
        "pair",
        "direction",
        "entry_price",
        "sl_price",
        "tp_price",
        "quantity",
        "opened_at",
        "capital_before",
    )

    def __init__(
        self,
        trade_id: str,
        pair: str,
        direction: TradeDirection,
        entry_price: Decimal,
        sl_price: Decimal,
        tp_price: Decimal,
        quantity: Decimal,
        opened_at: datetime,
        capital_before: Decimal,
    ) -> None:
        self.trade_id = trade_id
        self.pair = pair
        self.direction = direction
        self.entry_price = entry_price
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.quantity = quantity
        self.opened_at = opened_at
        self.capital_before = capital_before


class MockExecutor:
    """Exécuteur en mode dry-run : simule les trades sans appeler les endpoints d'ordre (NFR17).

    Respecte la même interface événementielle que TradeExecutor :
    - Souscrit à STRATEGY_SIGNAL_LONG/SHORT et CANDLE_CLOSED
    - Émet TRADE_OPENED et TRADE_CLOSED sur le bus

    Garanties :
    - connector.place_order() et connector.set_leverage() ne sont JAMAIS appelés (AC2, NFR17)
    - Seul connector.fetch_balance() est utilisé (endpoint lecture, AC4)
    """

    # Seuil minimum de capital pour ouvrir une position simulée (AC5, Story 9.2).
    # En dessous de ce seuil, aucun trade ne peut être ouvert (correspond à la taille minimale pratique).
    _MIN_VIABLE_CAPITAL: Decimal = Decimal("1")

    def __init__(
        self,
        connector: BaseExchangeConnector,
        event_bus: EventBus,
        config: StrategyConfig,
        capital_manager: BaseCapitalManager,
        trade_logger: TradeLogger,
    ) -> None:
        self._connector = connector
        self._event_bus = event_bus
        self._config = config
        self._capital_manager = capital_manager
        self._trade_logger = trade_logger
        self._open_trades: dict[str, _SimulatedTrade] = {}
        self._trades_count: int = 0  # Nombre de trades simulés fermés (AC6, Story 9.2)

        # Capital virtuel simulé — initialisé depuis initial_balance si présent (AC1, AC2, Story 9.2)
        if config.capital.initial_balance is not None:
            self._simulated_capital: Decimal | None = Decimal(str(config.capital.initial_balance))
            self._initial_capital: Decimal | None = self._simulated_capital
        else:
            self._simulated_capital = None  # Initialisé au premier trade depuis connector.fetch_balance()
            self._initial_capital = None

        self._handle_signal_long_bound = self._handle_signal_long
        self._handle_signal_short_bound = self._handle_signal_short
        self._handle_candle_bound = self._handle_candle_closed

        self._event_bus.on(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short_bound)  # type: ignore[arg-type]
        self._event_bus.on(EventType.CANDLE_CLOSED, self._handle_candle_bound)  # type: ignore[arg-type]

        logger.info("[DRY-RUN] Mode simulation actif")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    async def _handle_signal_long(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Signal LONG → ouvrir un trade simulé (AC2)."""
        if event.signal_price is None or event.sl_price is None:
            logger.warning(
                "[DRY-RUN] Signal LONG ignoré — signal_price ou sl_price manquant — pair={}",
                event.pair,
            )
            return
        await self._open_simulated_trade(
            event.pair, TradeDirection.LONG, event.signal_price, event.sl_price
        )

    async def _handle_signal_short(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        """Signal SHORT → ouvrir un trade simulé (AC2)."""
        if event.signal_price is None or event.sl_price is None:
            logger.warning(
                "[DRY-RUN] Signal SHORT ignoré — signal_price ou sl_price manquant — pair={}",
                event.pair,
            )
            return
        await self._open_simulated_trade(
            event.pair, TradeDirection.SHORT, event.signal_price, event.sl_price
        )

    # ------------------------------------------------------------------
    # Candle handler — détection TP/SL virtuelle
    # ------------------------------------------------------------------

    async def _handle_candle_closed(self, event: CandleEvent) -> None:  # type: ignore[arg-type]
        """Vérifie les TP/SL simulés à chaque bougie fermée (AC3)."""
        for trade_id in list(self._open_trades):
            trade = self._open_trades.get(trade_id)
            if trade is None or trade.pair != event.pair:
                continue

            exit_price: Decimal | None = None
            reason: str = ""

            if trade.direction == TradeDirection.LONG:
                if event.low <= trade.sl_price:
                    exit_price = trade.sl_price
                    reason = "SL"
                elif event.high >= trade.tp_price:
                    exit_price = trade.tp_price
                    reason = "TP"
            else:  # SHORT
                if event.high >= trade.sl_price:
                    exit_price = trade.sl_price
                    reason = "SL"
                elif event.low <= trade.tp_price:
                    exit_price = trade.tp_price
                    reason = "TP"

            if exit_price is not None:
                await self._close_simulated_trade(trade, exit_price, reason)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_simulated_trade(
        self,
        pair: str,
        direction: TradeDirection,
        signal_price: Decimal,
        sl_price: Decimal,
    ) -> None:
        """Ouvre un trade simulé : calcul TP/SL, émet TRADE_OPENED."""
        # Guard M2 : un seul trade simulé par paire à la fois
        if any(t.pair == pair for t in self._open_trades.values()):
            logger.warning("[DRY-RUN] Signal ignoré — trade déjà ouvert sur {}", pair)
            return

        # AC5 (Story 9.2) : capital insuffisant (< taille minimale de position) → pas de trade
        if self._simulated_capital is not None and self._simulated_capital < self._MIN_VIABLE_CAPITAL:
            logger.warning(
                "[WARN] Capital virtuel insuffisant pour ouvrir une position"
                " — capital={} < {} USDT minimum — pair={}",
                self._simulated_capital,
                self._MIN_VIABLE_CAPITAL,
                pair,
            )
            return

        try:
            # M3 : initialiser la balance simulée depuis l'exchange si initial_balance non fourni en config
            if self._simulated_capital is None:
                balance = await self._connector.fetch_balance()
                self._simulated_capital = balance.free
                self._initial_capital = balance.free  # AC1/AC2 (Story 9.2)
            capital_before = self._simulated_capital
            quantity = self._capital_manager.calculate_position_size(
                balance=capital_before,
                entry_price=signal_price,
                stop_loss=sl_price,
            )

            sl_distance = abs(signal_price - sl_price)
            if sl_distance == 0:
                logger.warning("[DRY-RUN] Distance SL invalide — signal ignoré")
                return

            rr = Decimal(str(self._config.capital.risk_reward_ratio))
            if direction == TradeDirection.LONG:
                real_sl = signal_price - sl_distance
                real_tp = signal_price + sl_distance * rr
            else:
                real_sl = signal_price + sl_distance
                real_tp = signal_price - sl_distance * rr

            trade_id = str(uuid.uuid4())
            trade = _SimulatedTrade(
                trade_id=trade_id,
                pair=pair,
                direction=direction,
                entry_price=signal_price,
                sl_price=real_sl,
                tp_price=real_tp,
                quantity=quantity,
                opened_at=datetime.now(timezone.utc),
                capital_before=capital_before,
            )
            self._open_trades[trade_id] = trade

            await self._event_bus.emit(
                EventType.TRADE_OPENED,
                TradeEvent(
                    event_type=EventType.TRADE_OPENED,
                    trade_id=trade_id,
                    pair=pair,
                    direction=direction.value,
                    entry_price=signal_price,
                    stop_loss=real_sl,
                    take_profit=real_tp,
                    quantity=quantity,
                    details=(
                        f"[DRY-RUN] entry={signal_price} sl={real_sl} tp={real_tp} qty={quantity}"
                    ),
                ),
            )
            logger.info(
                "[DRY-RUN] Trade simulé ouvert — trade_id={} pair={} direction={} entry={} sl={} tp={}",
                trade_id,
                pair,
                direction.value,
                signal_price,
                real_sl,
                real_tp,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[DRY-RUN] Erreur ouverture trade simulé — pair={} erreur={}", pair, exc)

    async def _close_simulated_trade(
        self,
        trade: _SimulatedTrade,
        exit_price: Decimal,
        reason: str,
    ) -> None:
        """Ferme un trade simulé, calcule le P&L, émet TRADE_CLOSED."""
        self._open_trades.pop(trade.trade_id, None)

        if trade.direction == TradeDirection.LONG:
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - exit_price) * trade.quantity

        duration = datetime.now(timezone.utc) - trade.opened_at
        capital_after = trade.capital_before + pnl
        self._simulated_capital = capital_after  # M3 : mettre à jour la balance simulée
        self._trades_count += 1  # AC6 (Story 9.2)

        result = TradeResult(
            trade_id=trade.trade_id,
            pair=trade.pair,
            direction=trade.direction,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            stop_loss=trade.sl_price,
            take_profit=trade.tp_price,
            leverage=self._config.leverage,
            pnl=pnl,
            duration=duration,
            capital_before=trade.capital_before,
            capital_after=capital_after,
            dry_run=True,  # AC3 (Story 9.2)
        )

        try:
            await self._trade_logger.log_trade(result)
        except Exception as exc:
            logger.warning("[DRY-RUN] Erreur log trade simulé — trade_id={} erreur={}", trade.trade_id, exc)

        await self._event_bus.emit(
            EventType.TRADE_CLOSED,
            TradeEvent(
                event_type=EventType.TRADE_CLOSED,
                trade_id=trade.trade_id,
                pair=trade.pair,
                direction=trade.direction.value,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                stop_loss=trade.sl_price,
                take_profit=trade.tp_price,
                pnl=pnl,
                capital_before=trade.capital_before,
                capital_after=capital_after,
                duration_seconds=duration.total_seconds(),
                details=f"[DRY-RUN] {reason} hit — exit={exit_price} pnl={pnl}",
            ),
        )
        logger.info(
            "[DRY-RUN] Trade simulé fermé — trade_id={} reason={} exit={} pnl={}",
            trade.trade_id,
            reason,
            exit_price,
            pnl,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Retourne le résumé de la session dry-run (AC6, Story 9.2).

        Returns:
            Dict avec initial_capital, final_capital, pnl_total, trades_count.
        """
        initial = self._initial_capital
        final = self._simulated_capital
        pnl_total = (final - initial) if (final is not None and initial is not None) else Decimal("0")
        return {
            "initial_capital": initial,
            "final_capital": final,
            "pnl_total": pnl_total,
            "trades_count": self._trades_count,
        }

    async def stop(self) -> None:
        """Désabonne les handlers du bus pour graceful shutdown."""
        self._event_bus.off(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long_bound)  # type: ignore[arg-type]
        self._event_bus.off(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short_bound)  # type: ignore[arg-type]
        self._event_bus.off(EventType.CANDLE_CLOSED, self._handle_candle_bound)  # type: ignore[arg-type]
        logger.debug("[DRY-RUN] MockExecutor arrêté — handlers retirés du bus")
