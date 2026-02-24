"""Tests pour StateManager — persistance d'état pour crash recovery (FR41, FR42, NFR11)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.state_manager import StateManager
from src.models.state import AppState, StrategyState, StrategyStateEnum


@pytest.fixture()
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "state.json"


@pytest.fixture()
def manager(state_path: Path) -> StateManager:
    return StateManager(state_path)


@pytest.fixture()
def default_state() -> AppState:
    return AppState()


class TestStateManagerSave:
    def test_save_creates_file(self, manager: StateManager, state_path: Path, default_state: AppState) -> None:
        """save() crée state.json s'il n'existe pas."""
        assert not state_path.exists()
        manager.save(default_state)
        assert state_path.exists()

    def test_save_creates_parent_directory_if_missing(self, tmp_path: Path, default_state: AppState) -> None:
        """save() crée le répertoire parent automatiquement."""
        deep_path = tmp_path / "nested" / "subdir" / "state.json"
        assert not deep_path.parent.exists()
        sm = StateManager(deep_path)
        sm.save(default_state)
        assert deep_path.exists()

    def test_save_writes_valid_json(self, manager: StateManager, state_path: Path, default_state: AppState) -> None:
        """save() écrit du JSON valide et lisible immédiatement après l'appel."""
        manager.save(default_state)
        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, dict)
        assert "strategy_states" in data
        assert "active_trades" in data

    def test_save_multiple_times_overwrites_correctly(self, manager: StateManager, state_path: Path) -> None:
        """Plusieurs save() successifs — le dernier état écrase le précédent."""
        state1 = AppState(active_trades=["trade-1"])
        state2 = AppState(active_trades=["trade-1", "trade-2"])
        state3 = AppState(active_trades=[])

        manager.save(state1)
        manager.save(state2)
        manager.save(state3)

        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["active_trades"] == []

    def test_save_with_complex_state(self, manager: StateManager, state_path: Path) -> None:
        """save() persiste correctement un AppState complexe avec stratégies et trades."""
        state = AppState(
            active_trades=["trade-abc-123"],
            strategy_states={
                "macd_cross": StrategyState(
                    state=StrategyStateEnum.IN_TRADE,
                    conditions_met=[0, 1],
                    current_trade_id="trade-abc-123",
                )
            },
        )
        manager.save(state)

        raw = state_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["active_trades"] == ["trade-abc-123"]
        assert "macd_cross" in data["strategy_states"]
        assert data["strategy_states"]["macd_cross"]["state"] == "IN_TRADE"
        assert data["strategy_states"]["macd_cross"]["conditions_met"] == [0, 1]

    def test_save_calls_fsync_for_nfr11(self, manager: StateManager, default_state: AppState) -> None:
        """save() appelle os.fsync() pour garantir la persistance disque (NFR11)."""
        with patch("src.core.state_manager.os.fsync") as mock_fsync:
            manager.save(default_state)
        mock_fsync.assert_called_once()

    def test_save_fsync_oserror_logs_warning_and_still_writes(
        self, manager: StateManager, state_path: Path, default_state: AppState
    ) -> None:
        """Si os.fsync() lève OSError : save() logue un warning ET écrit quand même le fichier."""
        with patch("src.core.state_manager.os.fsync", side_effect=OSError("fsync unavailable")):
            with patch("src.core.state_manager.logger.warning") as mock_warn:
                manager.save(default_state)
        assert state_path.exists()
        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "strategy_states" in data
        mock_warn.assert_called_once()


class TestStateManagerLoad:
    def test_load_returns_none_when_file_absent(self, manager: StateManager) -> None:
        """load() retourne None si state.json n'existe pas (premier démarrage)."""
        result = manager.load()
        assert result is None

    def test_load_returns_none_for_corrupted_json(
        self, manager: StateManager, state_path: Path
    ) -> None:
        """load() retourne None si state.json contient du JSON invalide."""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{ INVALID JSON !!! ", encoding="utf-8")
        result = manager.load()
        assert result is None

    def test_load_logs_warning_for_corrupted_json(
        self, manager: StateManager, state_path: Path
    ) -> None:
        """load() logue un warning quand le JSON est corrompu."""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("NOT JSON AT ALL", encoding="utf-8")
        with patch("src.core.state_manager.logger.warning") as mock_warn:
            manager.load()
        mock_warn.assert_called_once()
        assert "corrompu" in mock_warn.call_args[0][0]

    def test_load_returns_appstate_from_valid_file(
        self, manager: StateManager, state_path: Path, default_state: AppState
    ) -> None:
        """load() retourne l'AppState persisté depuis un fichier valide."""
        manager.save(default_state)
        result = manager.load()
        assert isinstance(result, AppState)

    def test_save_load_roundtrip_simple(self, manager: StateManager, default_state: AppState) -> None:
        """Round-trip save → load : AppState simple reconstruit correctement."""
        manager.save(default_state)
        loaded = manager.load()
        assert loaded is not None
        assert loaded.active_trades == []
        assert loaded.strategy_states == {}

    def test_save_load_roundtrip_complex(self, manager: StateManager) -> None:
        """Round-trip save → load : AppState complexe reconstruit correctement."""
        original = AppState(
            active_trades=["trade-xyz"],
            strategy_states={
                "rsi_strategy": StrategyState(
                    state=StrategyStateEnum.WATCHING,
                    conditions_met=[0],
                    current_trade_id=None,
                )
            },
        )
        manager.save(original)
        loaded = manager.load()

        assert loaded is not None
        assert loaded.active_trades == ["trade-xyz"]
        assert "rsi_strategy" in loaded.strategy_states
        assert loaded.strategy_states["rsi_strategy"].state == StrategyStateEnum.WATCHING
        assert loaded.strategy_states["rsi_strategy"].conditions_met == [0]

    def test_load_propagates_oserror_on_io_failure(
        self, manager: StateManager, state_path: Path
    ) -> None:
        """load() propage OSError pour les erreurs I/O (permission, disque) — pas de None silencieux."""
        from pathlib import Path as _Path

        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.touch()
        with patch.object(_Path, "read_text", side_effect=PermissionError("accès refusé")):
            with pytest.raises(PermissionError):
                manager.load()
