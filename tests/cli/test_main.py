"""Tests pour le CLI Click de trading-app."""

from click.testing import CliRunner

from src.cli.main import cli


class TestCliMain:
    """Tests du group CLI principal."""

    def test_cli_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "trading-app" in result.output

    def test_debug_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--debug", "status"])
        assert result.exit_code == 0

    def test_config_option(self):
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
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "start", "--strategy", "test"])
        assert result.exit_code == 0

    def test_trade_start_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["trade", "start"])
        assert result.exit_code != 0

    def test_trade_stop_recognized(self):
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
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run", "--strategy", "test"])
        assert result.exit_code == 0

    def test_backtest_run_requires_strategy(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["backtest", "run"])
        assert result.exit_code != 0


class TestStatusCommand:
    """Tests de la commande status."""

    def test_status_recognized(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
