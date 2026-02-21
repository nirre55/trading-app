"""Tests pour la commande CLI backtest run."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from src.backtest.metrics import BacktestMetrics, BacktestResult
from src.cli.main import cli


def _make_mock_result(total_trades: int = 5) -> BacktestResult:
    """Crée un BacktestResult mocké pour les tests."""
    mock_metrics = BacktestMetrics(
        total_trades=total_trades,
        win_rate=0.6,
        avg_rr=2.0,
        max_drawdown=0.05,
        max_consecutive_wins=3,
        max_consecutive_losses=2,
        profit_factor=1.5,
    )
    return BacktestResult(metrics=mock_metrics, trades=[])


class TestBacktestRun:
    """Tests de la commande backtest run."""

    def test_backtest_run_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run", "--help"])
        assert result.exit_code == 0
        assert "--from" in result.output
        assert "--to" in result.output

    def test_backtest_run_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run", "--from", "2024-01-01", "--to", "2024-12-31"])
        assert result.exit_code != 0

    def test_backtest_run_requires_from_to(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run", "--strategy", "test"])
        assert result.exit_code != 0

    def test_backtest_run_invalid_date_exits_2(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["backtest", "run", "--strategy", "test", "--from", "invalid", "--to", "2024-12-31"],
        )
        assert result.exit_code == 2

    def test_backtest_run_success(self):
        mock_result = _make_mock_result()
        with patch("src.cli.backtest.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_backtest = AsyncMock(return_value=mock_result)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["backtest", "run", "--strategy", "test", "--from", "2024-01-01", "--to", "2024-12-31"],
            )
            assert result.exit_code == 0
            assert "Win rate" in result.output

    def test_backtest_run_displays_all_metrics(self):
        mock_result = _make_mock_result(total_trades=10)
        with patch("src.cli.backtest.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_backtest = AsyncMock(return_value=mock_result)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["backtest", "run", "--strategy", "ma-strat", "--from", "2024-01-01", "--to", "2024-12-31"],
            )
            assert result.exit_code == 0
            assert "Trades total" in result.output
            assert "Ratio R:R" in result.output
            assert "Max drawdown" in result.output
            assert "Profit factor" in result.output

    def test_backtest_run_with_output_option(self, tmp_path):
        mock_result = _make_mock_result()
        output_file = str(tmp_path / "results.json")
        with patch("src.cli.backtest.TradingApp") as MockApp:
            mock_app = MagicMock()
            mock_app.run_backtest = AsyncMock(return_value=mock_result)
            MockApp.return_value = mock_app
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "backtest", "run", "--strategy", "test",
                    "--from", "2024-01-01", "--to", "2024-12-31",
                    "--output", output_file,
                ],
            )
            assert result.exit_code == 0
            assert "exportés" in result.output
