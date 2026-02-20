"""Moteur de replay pour backtesting sur données historiques."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger

from src.backtest.data_downloader import DataDownloader
from src.core.event_bus import EventBus
from src.models.events import CandleEvent, EventType

__all__ = ["ReplayEngine"]


class ReplayEngine:
    """Replay des données historiques OHLCV sur le bus d'événements (FR21, FR22).

    Alimente le bus avec des événements candle.closed identiques au live.
    Les modules (stratégie, capital manager) reçoivent les mêmes événements
    sans modification — c'est le cœur de l'invariant FR22.
    """

    def __init__(self, data_downloader: DataDownloader, event_bus: EventBus) -> None:
        self._downloader = data_downloader
        self._event_bus = event_bus
        logger.debug("ReplayEngine initialisé")

    @staticmethod
    def _ms_to_datetime(timestamp_ms: int) -> datetime:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

    async def run(
        self,
        exchange_name: str,
        pair: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> None:
        """Rejoue les bougies historiques en alimentant le bus (FR21, FR22)."""
        candles = await self._downloader.download(exchange_name, pair, timeframe, start_dt, end_dt)
        logger.info(
            "Replay démarré — {} bougies pour {} {} {}",
            len(candles), exchange_name, pair, timeframe,
        )
        for candle in candles:
            event = CandleEvent(
                event_type=EventType.CANDLE_CLOSED,
                timestamp=self._ms_to_datetime(int(candle[0])),
                pair=pair,
                timeframe=timeframe,
                open=Decimal(str(candle[1])),
                high=Decimal(str(candle[2])),
                low=Decimal(str(candle[3])),
                close=Decimal(str(candle[4])),
                volume=Decimal(str(candle[5])),
            )
            await self._event_bus.emit(EventType.CANDLE_CLOSED, event)
        logger.info("Replay terminé — {} bougies rejouées", len(candles))
