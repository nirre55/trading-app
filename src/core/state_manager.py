"""Gestionnaire de persistance d'état pour la reprise après crash."""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from src.models.state import AppState

__all__ = ["StateManager"]


class StateManager:
    """Persiste AppState sur disque pour crash recovery (FR41, FR42, NFR11).

    Utilisation :
        sm = StateManager(Path("data/state.json"))
        sm.save(app_state)    # flush immédiat
        state = sm.load()     # None si absent ou corrompu
    """

    def __init__(self, state_path: Path) -> None:
        self._path = state_path

    def save(self, app_state: AppState) -> None:
        """Sérialise AppState et écrit sur disque avec flush immédiat (NFR11)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            app_state.model_dump(mode="json"), ensure_ascii=False, default=str
        )
        self._write_atomic(data)
        logger.debug("💾 État persisté : {}", self._path)

    def load(self) -> AppState | None:
        """Charge AppState depuis state.json. Retourne None si absent ou corrompu."""
        if not self._path.exists():
            logger.debug("ℹ️ Pas de state.json — premier démarrage ou état nettoyé")
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(
                "❌ Impossible de lire state.json ({}: {}) — erreur I/O propagée",
                type(exc).__name__,
                exc,
            )
            raise
        try:
            data = json.loads(raw)
            state = AppState.model_validate(data)
            logger.info("📂 État restauré depuis {}", self._path)
            return state
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "⚠️ state.json corrompu — démarrage avec état vide ({}: {})",
                type(exc).__name__,
                exc,
            )
            return None

    def _write_atomic(self, data: str) -> None:
        """Écrit les données de façon atomique (write-to-temp + os.replace) avec fsync (NFR11).

        os.replace() est atomique sur POSIX (rename) et Windows (MoveFileExW) —
        le fichier final est toujours dans un état cohérent même en cas de crash.
        """
        tmp_path = self._path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError as exc:
                    logger.warning(
                        "⚠️ fsync non disponible sur ce système ({}) — données dans l'OS buffer",
                        exc,
                    )
            os.replace(tmp_path, self._path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
