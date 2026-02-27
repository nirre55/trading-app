"""Tests pour la commande CLI status."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.main import cli
from src.core.exceptions import ConfigError


class TestStatusCommand:
    """Tests de la commande status."""

    def test_status_no_session(self, tmp_path):
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = str(tmp_path / "state.json")
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Aucune session" in result.output

    def test_status_with_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({
                "uptime_start": datetime.now(timezone.utc).isoformat(),
                "active_trades": [],
                "strategy_states": {"ma-strat": {"state": "IDLE"}},
            })
        )
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = str(state_file)
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Uptime" in result.output

    def test_status_with_active_trades(self, tmp_path):
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({
                "uptime_start": datetime.now(timezone.utc).isoformat(),
                "active_trades": ["trade-001", "trade-002"],
                "strategy_states": {"ma-strat": {"state": "IN_TRADE"}},
            })
        )
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = str(state_file)
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Trades actifs" in result.output
            assert "IN_TRADE" in result.output

    def test_status_fallback_when_config_error(self, tmp_path):
        with patch("src.cli.status.load_app_config", side_effect=ConfigError("config error")):
            runner = CliRunner()
            # Exécution dans un répertoire temporaire : data/state.json est absent
            with runner.isolated_filesystem():
                result = runner.invoke(cli, ["status"])
            # Fallback sur data/state.json absent → affiche "Aucune session"
            assert result.exit_code == 0
            assert "Aucune session" in result.output
