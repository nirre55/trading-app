"""Simulateur de trades pour backtesting (exécution fictive des ordres)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from loguru import logger

from src.capital.base import BaseCapitalManager
from src.core.event_bus import EventBus
from src.models.config import StrategyConfig
from src.models.events import CandleEvent, EventType, StrategyEvent, TradeEvent
from src.models.trade import TradeDirection, TradeRecord, TradeResult, TradeStatus

__all__ = ["TradeSimulator"]

FEE_RATE = Decimal("0.001")  # 0.1% par côté (entrée + sortie) — FR23


class TradeSimulator:
    """Simulateur de trades backtest — remplace TradeExecutor en mode backtest.

    Écoute les signaux strategy.* et les bougies candle.closed.
    Simule l'exécution des ordres avec frais 0.1% entrée + 0.1% sortie (FR23).
    Détecte les hits TP/SL sur chaque bougie (FR22).
    Maintient la liste des TradeResult pour le calcul des métriques (Story 5.3).
    """

    def __init__(
        self,
        event_bus: EventBus,
        config: StrategyConfig,
        capital_manager: BaseCapitalManager,
        initial_capital: Decimal,
    ) -> None:
        self._event_bus = event_bus
        self._config = config
        self._capital_manager = capital_manager
        self._balance = initial_capital
        self._open_trade: TradeRecord | None = None
        self._closed_trades: list[TradeResult] = []
        self._event_bus.on(EventType.STRATEGY_SIGNAL_LONG, self._handle_signal_long)  # type: ignore[arg-type]
        self._event_bus.on(EventType.STRATEGY_SIGNAL_SHORT, self._handle_signal_short)  # type: ignore[arg-type]
        self._event_bus.on(EventType.CANDLE_CLOSED, self._handle_candle_closed)  # type: ignore[arg-type]
        logger.debug("TradeSimulator initialisé — capital_initial={}", initial_capital)

    @property
    def closed_trades(self) -> list[TradeResult]:
        """Liste des TradeResult clôturés — pour Story 5.3 (métriques)."""
        return list(self._closed_trades)

    def _calculate_tp(
        self, direction: TradeDirection, entry_price: Decimal, sl_price: Decimal
    ) -> Decimal:
        sl_distance = abs(entry_price - sl_price)
        rr = Decimal(str(self._config.capital.risk_reward_ratio))
        if direction == TradeDirection.LONG:
            return entry_price + sl_distance * rr
        return entry_price - sl_distance * rr

    async def _handle_signal_long(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        if self._open_trade is not None:
            logger.warning("Signal LONG ignoré — trade déjà ouvert — pair={}", event.pair)
            return
        if event.signal_price is None or event.sl_price is None:
            logger.warning("Signal LONG ignoré — signal_price ou sl_price manquant")
            return
        await self._open_trade_sim(event, TradeDirection.LONG)

    async def _handle_signal_short(self, event: StrategyEvent) -> None:  # type: ignore[arg-type]
        if self._open_trade is not None:
            logger.warning("Signal SHORT ignoré — trade déjà ouvert — pair={}", event.pair)
            return
        if event.signal_price is None or event.sl_price is None:
            logger.warning("Signal SHORT ignoré — signal_price ou sl_price manquant")
            return
        await self._open_trade_sim(event, TradeDirection.SHORT)

    async def _open_trade_sim(self, event: StrategyEvent, direction: TradeDirection) -> None:
        if event.signal_price is None or event.sl_price is None:
            return  # Garanti non-None par les handlers appelants ; garde pour mypy et sécurité
        quantity = self._capital_manager.calculate_position_size(
            self._balance, event.signal_price, event.sl_price
        )
        tp_price = self._calculate_tp(direction, event.signal_price, event.sl_price)
        trade_id = str(uuid.uuid4())
        self._open_trade = TradeRecord(
            id=trade_id,
            pair=event.pair,
            direction=direction,
            entry_price=event.signal_price,
            stop_loss=event.sl_price,
            take_profit=tp_price,
            leverage=self._config.leverage,
            quantity=quantity,
            status=TradeStatus.OPEN,
            capital_before=self._balance,
        )
        await self._event_bus.emit(
            EventType.TRADE_OPENED,
            TradeEvent(
                event_type=EventType.TRADE_OPENED,
                trade_id=trade_id,
                pair=event.pair,
                details=f"entry={event.signal_price} sl={event.sl_price} tp={tp_price}",
            ),
        )
        logger.info(
            "Trade simulé ouvert {} — entry={} sl={} tp={}",
            direction, event.signal_price, event.sl_price, tp_price,
        )

    async def _handle_candle_closed(self, event: CandleEvent) -> None:  # type: ignore[arg-type]
        if self._open_trade is None:
            return
        trade = self._open_trade
        if event.pair != trade.pair:
            return
        # SL prioritaire si les deux sont touchés dans la même bougie (AC4)
        if trade.direction == TradeDirection.LONG:
            sl_hit = event.low <= trade.stop_loss
            tp_hit = event.high >= trade.take_profit
        else:
            sl_hit = event.high >= trade.stop_loss
            tp_hit = event.low <= trade.take_profit

        if sl_hit:
            await self._close_trade(trade, trade.stop_loss, EventType.TRADE_SL_HIT, exit_timestamp=event.timestamp)
        elif tp_hit:
            await self._close_trade(trade, trade.take_profit, EventType.TRADE_TP_HIT, exit_timestamp=event.timestamp)

    async def _close_trade(
        self,
        trade: TradeRecord,
        exit_price: Decimal,
        close_event_type: EventType,
        exit_timestamp: datetime | None = None,
    ) -> None:
        entry_fee = trade.entry_price * trade.quantity * FEE_RATE
        exit_fee = exit_price * trade.quantity * FEE_RATE
        if trade.direction == TradeDirection.LONG:
            gross_pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            gross_pnl = (trade.entry_price - exit_price) * trade.quantity
        net_pnl = gross_pnl - entry_fee - exit_fee
        self._balance = trade.capital_before + net_pnl
        # En backtest, exit_timestamp est le timestamp de la bougie historique.
        # trade.timestamp est wall-clock (domaines différents → durée précise impossible ici).
        # timedelta(0) est un placeholder explicite ; calcul exact requiert entry_candle_timestamp
        # dans TradeRecord — TODO Story 5.3+ pour métriques de durée fiables.
        if exit_timestamp is not None:
            duration = timedelta(0)
        else:
            duration = datetime.now(timezone.utc) - trade.timestamp
        result = TradeResult(
            trade_id=str(trade.id),
            pair=trade.pair,
            direction=trade.direction,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            leverage=trade.leverage,
            pnl=net_pnl,
            duration=duration,
            capital_before=trade.capital_before,
            capital_after=self._balance,
        )
        self._closed_trades.append(result)
        self._open_trade = None
        await self._event_bus.emit(
            close_event_type,
            TradeEvent(
                event_type=close_event_type,
                trade_id=str(trade.id),
                pair=trade.pair,
                exit_price=exit_price,
                pnl=net_pnl,
            ),
        )
        await self._event_bus.emit(
            EventType.TRADE_CLOSED,
            TradeEvent(
                event_type=EventType.TRADE_CLOSED,
                trade_id=str(trade.id),
                pair=trade.pair,
                exit_price=exit_price,
                pnl=net_pnl,
                capital_before=trade.capital_before,
                capital_after=self._balance,
            ),
        )
        logger.info(
            "Trade simulé clôturé — pnl={} capital_après={}", net_pnl, self._balance
        )
