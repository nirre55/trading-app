"""Logging structuré des trades en format JSON."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.models.trade import TradeResult


class TradeLogger:
    """Enregistre chaque trade clôturé en JSONL horodaté (FR31, NFR11, NFR14).

    Format : data/trades/YYYY-MM-DD.jsonl — un enregistrement JSON par ligne.
    Flush immédiat après chaque écriture (NFR11) — crash-safe.
    """

    def __init__(self, trades_dir: str | Path) -> None:
        self._trades_dir = Path(trades_dir)
        self._trades_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("TradeLogger initialisé — répertoire={}", self._trades_dir)

    async def log_trade(self, result: TradeResult) -> None:
        """Enregistre un trade clôturé en JSONL avec flush immédiat (FR31, NFR11)."""
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            file_path = self._trades_dir / f"{today}.jsonl"

            # model_dump(mode="json") : Decimal→str, datetime→ISO 8601
            record = result.model_dump(mode="json")

            # Convertir timedelta en secondes flottantes — indépendant du comportement Pydantic (NFR14/AC4)
            record["duration"] = result.duration.total_seconds()

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())  # Flush complet vers le disque (NFR11)

            logger.info(
                "Trade loggé — trade_id={} pair={} pnl={} fichier={}",
                result.trade_id,
                result.pair,
                result.pnl,
                file_path,
            )
        except Exception as exc:
            logger.exception(
                "Erreur logging trade — trade_id={} erreur={}", result.trade_id, exc
            )
