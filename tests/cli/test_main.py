"""Tests pour le CLI Click de trading-app."""

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from src.backtest.metrics import BacktestMetrics, BacktestResult
from src.cli.main import cli


class TestCliMain:
    """Tests du group CLI principal."""

    def test_cli_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "trading-app" in result.output

    def test_debug_flag(self):
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = "/nonexistent/state.json"
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["--debug", "status"])
            assert result.exit_code == 0

    def test_config_option(self):
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = "/nonexistent/state.json"
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["-c", "/tmp/test.yaml", "status"])
            assert result.exit_code == 0


class TestTradeGroup:
    """Tests du sous-groupe trade."""

    def test_trade_group_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output

    def test_trade_start_recognized(self):
        with patch("src.cli.trade.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_live = AsyncMock(return_value=None)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
            assert result.exit_code == 0

    def test_trade_start_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "start"])
        assert result.exit_code != 0

    def test_trade_stop_recognized(self):
        with patch("src.cli.trade.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = "/tmp/state.json"
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["trade", "stop"])
            assert result.exit_code == 0


class TestBacktestGroup:
    """Tests du sous-groupe backtest."""

    def test_backtest_group_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_backtest_run_recognized(self):
        mock_metrics = BacktestMetrics(
            total_trades=0, win_rate=0.0, avg_rr=0.0,
            max_drawdown=0.0, max_consecutive_wins=0,
            max_consecutive_losses=0, profit_factor=0.0,
        )
        mock_result = BacktestResult(metrics=mock_metrics, trades=[])
        with patch("src.cli.backtest.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_backtest = AsyncMock(return_value=mock_result)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(cli, ["backtest", "run", "--strategy", "test",
                                        "--from", "2024-01-01", "--to", "2024-12-31"])
            assert result.exit_code == 0

    def test_backtest_run_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run"])
        assert result.exit_code != 0


class TestStatusCommand:
    """Tests de la commande status."""

    def test_status_recognized(self):
        with patch("src.cli.status.load_app_config") as mock_cfg:
            mock_c = MagicMock()
            mock_c.paths.state = "/nonexistent/state.json"
            mock_cfg.return_value = mock_c
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
