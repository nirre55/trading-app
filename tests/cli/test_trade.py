"""Tests pour les commandes CLI trade start/stop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from src.cli.main import cli
from src.core.exceptions import ConfigError, ExchangeError, InsufficientBalanceError


class TestTradeStart:
    """Tests de la commande trade start."""

    def test_trade_start_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "start", "--help"])
        assert result.exit_code == 0
        assert "--strategy" in result.output

    def test_trade_start_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "start"])
        assert result.exit_code != 0

    def test_trade_start_success(self):
        with patch("src.cli.trade.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_live = AsyncMock(return_value=None)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
            assert result.exit_code == 0

    def test_trade_start_config_error_exits_1(self):
        with patch("src.cli.trade.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_live = AsyncMock(side_effect=ConfigError("config manquante"))
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
            assert result.exit_code == 1

    def test_trade_start_exchange_error_exits_1(self):
        with patch("src.cli.trade.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_live = AsyncMock(side_effect=ExchangeError("connexion impossible"))
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
            assert result.exit_code == 1

    def test_trade_start_insufficient_balance_exits_1(self):
        with patch("src.cli.trade.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_live = AsyncMock(
                side_effect=InsufficientBalanceError("balance trop faible")
            )
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
            assert result.exit_code == 1


class TestTradeStop:
    """Tests de la commande trade stop."""

    def test_trade_stop_creates_stop_flag(self, tmp_path):
        with patch("src.cli.trade.load_app_config") as mock_config:
            mock_cfg = MagicMock()
            # Simuler config.paths.state = str(tmp_path / "state.json")
            # trade stop fait: Path(config.paths.state).parent / "stop.flag"
            mock_cfg.paths.state = str(tmp_path / "state.json")
            mock_config.return_value = mock_cfg
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "stop"])
            assert result.exit_code == 0
            assert (tmp_path / "stop.flag").exists()

    def test_trade_stop_message(self, tmp_path):
        with patch("src.cli.trade.load_app_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.paths.state = str(tmp_path / "state.json")
            mock_config.return_value = mock_cfg
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "stop"])
            assert result.exit_code == 0
            assert "Signal d'arrêt" in result.output
