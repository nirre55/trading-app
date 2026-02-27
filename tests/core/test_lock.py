"""Tests pour LockFile — prévention double instance (FR40)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.exceptions import LockError
from src.core.lock import LockFile, _is_process_running


@pytest.fixture()
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "trading.lock"


class TestLockFileAcquire:
    def test_acquire_creates_lock_file(self, lock_path: Path) -> None:
        lock = LockFile(lock_path)
        lock.acquire()
        assert lock_path.exists()
        lock.release()

    def test_acquire_writes_pid_and_timestamp(self, lock_path: Path) -> None:
        lock = LockFile(lock_path)
        lock.acquire()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert "started_at" in data
        lock.release()

    def test_acquire_creates_parent_dir_if_missing(self, tmp_path: Path) -> None:
        deep_lock = tmp_path / "subdir" / "trading.lock"
        assert not deep_lock.parent.exists()
        lock = LockFile(deep_lock)
        lock.acquire()
        assert deep_lock.exists()
        lock.release()

    def test_acquire_raises_lockError_when_active_instance(self, lock_path: Path) -> None:
        """Lock existe avec PID actif → LockError levée."""
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": "2026-01-01T00:00:00"}),
            encoding="utf-8",
        )
        with pytest.raises(LockError, match="déjà active"):
            LockFile(lock_path).acquire()

    def test_acquire_removes_stale_lock_and_proceeds(self, lock_path: Path) -> None:
        """Lock avec PID inexistant → traité comme périmé, suppression et démarrage."""
        # PID 99999 est quasi-certain d'être inexistant
        lock_path.write_text(
            json.dumps({"pid": 99999999, "started_at": "2025-01-01T00:00:00"}),
            encoding="utf-8",
        )
        with patch("src.core.lock._is_process_running", return_value=False):
            lock = LockFile(lock_path)
            lock.acquire()  # Ne doit pas lever
            assert lock_path.exists()
            lock.release()

    def test_acquire_removes_corrupted_lock_and_proceeds(self, lock_path: Path) -> None:
        """Lock corrompu (JSON invalide) → traité comme périmé."""
        lock_path.write_text("NOT VALID JSON ###", encoding="utf-8")
        lock = LockFile(lock_path)
        lock.acquire()
        assert lock_path.exists()
        lock.release()


class TestLockFileRelease:
    def test_release_deletes_lock_file(self, lock_path: Path) -> None:
        lock = LockFile(lock_path)
        lock.acquire()
        assert lock_path.exists()
        lock.release()
        assert not lock_path.exists()

    def test_release_noop_if_no_lock_file(self, lock_path: Path) -> None:
        """release() ne lève pas si le fichier est absent."""
        assert not lock_path.exists()
        LockFile(lock_path).release()  # Ne doit pas lever


class TestLockFileContextManager:
    def test_context_manager_acquires_and_releases(self, lock_path: Path) -> None:
        with LockFile(lock_path):
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_context_manager_releases_on_exception(self, lock_path: Path) -> None:
        try:
            with LockFile(lock_path):
                assert lock_path.exists()
                raise ValueError("test error")
        except ValueError:
            pass
        assert not lock_path.exists()


class TestIsProcessRunning:
    def test_current_process_is_running(self) -> None:
        assert _is_process_running(os.getpid()) is True

    def test_nonexistent_pid_is_not_running(self) -> None:
        with patch("src.core.lock.os.kill", side_effect=ProcessLookupError):
            assert _is_process_running(99999999) is False

    def test_permission_error_means_process_is_running(self) -> None:
        """PermissionError : PID existe mais accès refusé → considéré actif."""
        with patch("src.core.lock.os.kill", side_effect=PermissionError):
            assert _is_process_running(99999999) is True

    def test_os_error_windows_delegates_to_tasklist(self) -> None:
        """OSError sur Windows → délègue à _is_process_running_windows (tasklist)."""
        with patch("src.core.lock.os.kill", side_effect=OSError("invalid argument")), \
             patch("src.core.lock.sys.platform", "win32"), \
             patch("src.core.lock._is_process_running_windows", return_value=True) as mock_win:
            assert _is_process_running(99999999) is True
            mock_win.assert_called_once_with(99999999)

    def test_os_error_non_windows_assumes_running(self) -> None:
        """OSError sur OS non-Windows → assumer actif par sécurité (comportement conservatif)."""
        with patch("src.core.lock.os.kill", side_effect=OSError("invalid argument")), \
             patch("src.core.lock.sys.platform", "linux"):
            assert _is_process_running(99999999) is True

    def test_windows_tasklist_dead_pid_returns_false(self) -> None:
        """_is_process_running_windows retourne False pour un PID inexistant."""
        from src.core.lock import _is_process_running_windows
        # PID 99999999 n'existe pas → tasklist ne le trouve pas → False
        assert _is_process_running_windows(99999999) is False

    def test_windows_tasklist_current_pid_returns_true(self) -> None:
        """_is_process_running_windows retourne True pour le PID courant."""
        import os as _os
        from src.core.lock import _is_process_running_windows
        assert _is_process_running_windows(_os.getpid()) is True
