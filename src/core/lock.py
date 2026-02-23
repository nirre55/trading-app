"""Lock file pour prévenir les doubles instances de l'application."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import TracebackType

from loguru import logger

from src.core.exceptions import LockError

__all__ = ["LockFile"]


class LockFile:
    """Gestionnaire de fichier de lock anti-double instance (FR40).

    Utilisation en contexte :
        with LockFile(Path("data/trading.lock")):
            # application en cours d'exécution
    """

    def __init__(self, lock_path: Path) -> None:
        self._path = lock_path

    def acquire(self) -> None:
        """Crée le lock file. Lève LockError si une instance active est détectée."""
        if self._path.exists():
            self._handle_existing_lock()
        self._write_lock()
        logger.info("🔒 Lock acquis : {}", self._path)

    def release(self) -> None:
        """Supprime le lock file (no-op si absent)."""
        self._path.unlink(missing_ok=True)
        logger.info("🔓 Lock libéré : {}", self._path)

    def _write_lock(self) -> None:
        """Écrit le fichier de lock avec PID et timestamp courants."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {"pid": os.getpid(), "started_at": datetime.now().isoformat()}
            ),
            encoding="utf-8",
        )

    def _handle_existing_lock(self) -> None:
        """Gère un lock existant : vérifie si périmé ou instance active."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            logger.warning("⚠️ Lock file corrompu — suppression et démarrage")
            self._path.unlink(missing_ok=True)
            return

        if not _is_process_running(pid):
            logger.warning(
                "⚠️ Lock file périmé détecté (PID {} inactif) — suppression et démarrage",
                pid,
            )
            self._path.unlink(missing_ok=True)
            return

        raise LockError(
            f"Une instance est déjà active (PID {pid}). "
            f"Arrêtez-la avec `trade stop` ou supprimez {self._path}."
        )

    def __enter__(self) -> LockFile:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()


def _is_process_running(pid: int) -> bool:
    """Vérifie si un processus est actif (cross-platform sans dépendance externe).

    Args:
        pid: PID du processus à vérifier.

    Returns:
        True si le processus est actif, False sinon.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # ESRCH : PID inexistant → périmé
        return False
    except PermissionError:
        # EPERM : PID existe mais permission refusée → toujours actif
        return True
    except OSError:
        # Fallback Windows ou autre erreur OS → assumer actif par sécurité
        return True
