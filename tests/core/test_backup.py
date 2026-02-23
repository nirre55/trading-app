"""Tests pour LogBackupService."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.backup import LogBackupService


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture()
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


class TestDoBackup:
    def test_copies_log_files(self, log_dir: Path, backup_dir: Path) -> None:
        (log_dir / "trading_2026-02-23.log").write_text("log content")
        service = LogBackupService()
        count = service.do_backup(log_dir, backup_dir)
        assert count == 1
        # Vérifie qu'un sous-répertoire timestampé a été créé avec le fichier
        copied = list(backup_dir.rglob("trading_2026-02-23.log"))
        assert len(copied) == 1

    def test_copies_zip_files(self, log_dir: Path, backup_dir: Path) -> None:
        (log_dir / "trading_2026-02-22.log.zip").write_bytes(b"zip content")
        service = LogBackupService()
        count = service.do_backup(log_dir, backup_dir)
        assert count == 1
        copied = list(backup_dir.rglob("trading_2026-02-22.log.zip"))
        assert len(copied) == 1

    def test_copies_multiple_files(self, log_dir: Path, backup_dir: Path) -> None:
        (log_dir / "trading_2026-02-23.log").write_text("a")
        (log_dir / "trading_2026-02-22.log.zip").write_bytes(b"b")
        service = LogBackupService()
        count = service.do_backup(log_dir, backup_dir)
        assert count == 2

    def test_creates_backup_dir_if_missing(self, log_dir: Path, backup_dir: Path) -> None:
        assert not backup_dir.exists()
        (log_dir / "trading.log").write_text("x")
        LogBackupService().do_backup(log_dir, backup_dir)
        assert backup_dir.exists()

    def test_noop_when_no_files(self, log_dir: Path, backup_dir: Path) -> None:
        """Aucun fichier → retourne 0, aucune erreur."""
        count = LogBackupService().do_backup(log_dir, backup_dir)
        assert count == 0
        # Aucun répertoire timestampé créé (no-op)
        assert not backup_dir.exists()

    def test_logs_success_message(self, log_dir: Path, backup_dir: Path) -> None:
        (log_dir / "trading.log").write_text("content")
        with patch("src.core.backup.logger") as mock_logger:
            count = LogBackupService().do_backup(log_dir, backup_dir)
        assert count == 1
        mock_logger.info.assert_called_once()
        # loguru utilise logger.info(template, arg1, arg2) — args[0] est le template
        args = mock_logger.info.call_args[0]
        assert "Backup logs réussi" in args[0]
        assert "fichier(s)" in args[0]
        assert "copié(s)" in args[0]
        assert "vers" in args[0]
        assert args[1] == 1  # nombre de fichiers copiés

    def test_raises_on_missing_log_dir(self, tmp_path: Path, backup_dir: Path) -> None:
        """log_dir inexistant → OSError propagée (appelant doit gérer)."""
        missing = tmp_path / "nonexistent"
        with pytest.raises(OSError):
            LogBackupService().do_backup(missing, backup_dir)

    @pytest.mark.asyncio
    async def test_run_loop_cancels_cleanly(self, log_dir: Path, backup_dir: Path) -> None:
        """La boucle run() s'arrête proprement sur CancelledError."""
        service = LogBackupService()
        task = asyncio.create_task(service.run(log_dir, backup_dir, interval_hours=9999))
        await asyncio.sleep(0)  # Laisser la coroutine démarrer
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_run_catches_do_backup_error(
        self, tmp_path: Path, backup_dir: Path
    ) -> None:
        """Si do_backup lève une exception, run() la logge (ERROR) et continue sans crasher."""
        service = LogBackupService()
        call_count = 0

        def _failing_backup(log_dir: Path, backup_dir: Path) -> int:
            nonlocal call_count
            call_count += 1
            raise OSError("Disk full")

        service.do_backup = _failing_backup  # type: ignore[method-assign]
        with patch("src.core.backup.logger") as mock_logger:
            # interval_hours=0 → sleep(0) → exécution immédiate en boucle
            task = asyncio.create_task(service.run(tmp_path, backup_dir, interval_hours=0))
            await asyncio.sleep(0.05)  # 50ms — suffit pour plusieurs itérations
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert call_count > 0, "do_backup doit avoir été appelé au moins une fois"
            mock_logger.error.assert_called()  # AC3 : l'erreur ERROR est bien loggée


class TestConfigBackupOptionnelle:
    """AC6 : Les champs backup sont optionnels — les valeurs par défaut s'appliquent."""

    def test_paths_backup_default_when_absent(self) -> None:
        """PathsConfig.backup vaut 'data/backups' si absent de la config."""
        from src.models.config import PathsConfig

        config = PathsConfig(logs="data/logs", trades="data/trades", state="data/state.json")
        assert config.backup == "data/backups"

    def test_backup_interval_hours_default_when_absent(self) -> None:
        """DefaultsConfig.backup_interval_hours vaut 24 si absent de la config."""
        from src.models.config import DefaultsConfig

        config = DefaultsConfig()
        assert config.backup_interval_hours == 24
