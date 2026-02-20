"""Téléchargement de données historiques OHLCV depuis les exchanges."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import ccxt.async_support as ccxt_async
from loguru import logger

__all__ = ["DataDownloader"]

CANDLES_PER_REQUEST = 1000


class DataDownloader:
    """Télécharge et met en cache les données OHLCV historiques via CCXT REST (FR25).

    Cache local : {data_dir}/{exchange}/{pair_safe}/{timeframe}/{start}_{end}.json
    Réutilise le cache sans appel réseau si le fichier existe déjà.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("DataDownloader initialisé — répertoire={}", self._data_dir)

    def _get_cache_path(
        self,
        exchange_name: str,
        pair: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Path:
        pair_safe = pair.replace("/", "_")
        start_str = start_dt.strftime("%Y-%m-%dT%H%M%S")  # inclut l'heure — évite collision de cache
        end_str = end_dt.strftime("%Y-%m-%dT%H%M%S")
        return self._data_dir / exchange_name / pair_safe / timeframe / f"{start_str}_{end_str}.json"

    def _save_to_cache(self, cache_path: Path, candles: list[list]) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(candles, f)
        tmp_path.replace(cache_path)  # renommage atomique — évite la corruption partielle
        logger.info("Données sauvegardées : {} bougies dans {}", len(candles), cache_path)

    def _load_from_cache(self, cache_path: Path) -> list[list]:
        with open(cache_path, encoding="utf-8") as f:
            candles: list[list] = json.load(f)
        logger.info("Cache hit : {} bougies chargées depuis {}", len(candles), cache_path)
        return candles

    async def _fetch_ohlcv_paginated(
        self,
        exchange: Any,
        pair: str,
        timeframe: str,
        since_ms: int,
        until_ms: int,
    ) -> list[list]:
        """Pagine les appels fetch_ohlcv jusqu'à couvrir toute la plage [since_ms, until_ms)."""
        candles: list[list] = []
        current_since = since_ms

        while current_since < until_ms:
            batch = await exchange.fetch_ohlcv(
                pair, timeframe, since=current_since, limit=CANDLES_PER_REQUEST
            )
            if not batch:
                break

            in_range = [c for c in batch if c[0] < until_ms]
            candles.extend(in_range)

            if len(batch) < CANDLES_PER_REQUEST:
                break  # dernier batch, plus de données disponibles

            current_since = batch[-1][0] + 1

        if candles:
            logger.info("Téléchargement terminé : {} bougies récupérées pour {}", len(candles), pair)
        else:
            logger.warning("Aucune bougie récupérée pour {} {}", pair, timeframe)
        return candles

    async def download(
        self,
        exchange_name: str,
        pair: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[list]:
        """Télécharge les données OHLCV, utilise le cache si disponible (FR25)."""
        if start_dt.tzinfo is None or end_dt.tzinfo is None:
            raise ValueError(
                "start_dt et end_dt doivent être timezone-aware (ex: tzinfo=timezone.utc)"
            )

        cache_path = self._get_cache_path(exchange_name, pair, timeframe, start_dt, end_dt)

        if cache_path.exists():
            try:
                return self._load_from_cache(cache_path)
            except json.JSONDecodeError:
                logger.warning(
                    "Cache corrompu ({}) — suppression et re-téléchargement", cache_path
                )
                cache_path.unlink(missing_ok=True)

        logger.info(
            "Téléchargement {} {} {} du {} au {}",
            exchange_name,
            pair,
            timeframe,
            start_dt.date(),
            end_dt.date(),
        )

        exchange_class = getattr(ccxt_async, exchange_name)
        exchange = exchange_class({"enableRateLimit": True})

        try:
            candles = await self._fetch_ohlcv_paginated(
                exchange,
                pair,
                timeframe,
                int(start_dt.timestamp() * 1000),
                int(end_dt.timestamp() * 1000),
            )
        finally:
            await exchange.close()

        if candles:
            self._save_to_cache(cache_path, candles)
        else:
            logger.warning(
                "Aucune bougie pour {} {} {} [{} → {}] — cache non sauvegardé",
                exchange_name, pair, timeframe, start_dt.date(), end_dt.date(),
            )
        return candles
