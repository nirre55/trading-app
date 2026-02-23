"""Service de backup périodique des fichiers de logs."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

__all__ = ["LogBackupService"]


class LogBackupService:
    """Backup périodique des fichiers de logs vers un emplacement désigné (FR32)."""

    async def run(self, log_dir: Path, backup_dir: Path, interval_hours: int) -> None:
        """Boucle async de backup — tourne jusqu'à annulation asyncio.

        Args:
            log_dir: Répertoire source des logs (data/logs/).
            backup_dir: Répertoire de destination des backups.
            interval_hours: Intervalle entre chaque backup, en heures.
        """
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                self.do_backup(log_dir, backup_dir)
            except Exception as e:
                logger.error("Échec du backup des logs : {}", e)

    def do_backup(self, log_dir: Path, backup_dir: Path) -> int:
        """Copie les fichiers logs vers backup_dir/{timestamp}/.

        Args:
            log_dir: Répertoire source contenant les fichiers *.log et *.log.zip.
            backup_dir: Répertoire de destination (sera créé si absent).

        Returns:
            Nombre de fichiers copiés.

        Raises:
            OSError: Si log_dir est inaccessible ou la destination inaccessible.
        """
        if not log_dir.is_dir():
            raise OSError(f"log_dir inexistant ou inaccessible : {log_dir}")

        files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.log.zip"))
        if not files:
            return 0

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / timestamp
        dest.mkdir(parents=True, exist_ok=True)

        copied = 0
        for f in files:
            try:
                shutil.copy2(f, dest / f.name)
                copied += 1
            except OSError as e:
                logger.error("Échec de la copie de {} : {}", f.name, e)

        if copied > 0:
            logger.info("Backup logs réussi : {} fichier(s) copié(s) vers {}", copied, dest)
        return copied
