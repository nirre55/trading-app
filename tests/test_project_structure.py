"""Tests de validation de la structure du projet et de l'initialisation."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


class TestProjectStructure:
    """Vérifie que l'arborescence du projet est complète (AC #3)."""

    @pytest.mark.parametrize(
        "package",
        [
            "src",
            "src/cli",
            "src/core",
            "src/models",
            "src/exchange",
            "src/strategies",
            "src/capital",
            "src/indicators",
            "src/trading",
            "src/backtest",
        ],
    )
    def test_src_packages_have_init(self, package: str) -> None:
        init_file = PROJECT_ROOT / package / "__init__.py"
        assert init_file.exists(), f"{package}/__init__.py manquant"

    @pytest.mark.parametrize(
        "package",
        [
            "tests",
            "tests/cli",
            "tests/core",
            "tests/models",
            "tests/exchange",
            "tests/strategies",
            "tests/capital",
            "tests/indicators",
            "tests/trading",
            "tests/backtest",
        ],
    )
    def test_tests_packages_have_init(self, package: str) -> None:
        init_file = PROJECT_ROOT / package / "__init__.py"
        assert init_file.exists(), f"{package}/__init__.py manquant"

    @pytest.mark.parametrize(
        "filepath",
        [
            "src/cli/main.py",
            "src/core/event_bus.py",
            "src/core/state_machine.py",
            "src/core/config.py",
            "src/core/app.py",
            "src/core/state_manager.py",
            "src/core/logging.py",
            "src/core/lock.py",
            "src/core/exceptions.py",
            "src/models/events.py",
            "src/models/trade.py",
            "src/models/config.py",
            "src/models/state.py",
            "src/models/exchange.py",
            "src/exchange/base.py",
            "src/exchange/ccxt_connector.py",
            "src/exchange/rate_limiter.py",
            "src/exchange/order_validator.py",
            "src/strategies/base.py",
            "src/strategies/registry.py",
            "src/capital/base.py",
            "src/capital/registry.py",
            "src/capital/fixed_percent.py",
            "src/indicators/base.py",
            "src/indicators/registry.py",
            "src/indicators/rsi.py",
            "src/trading/trade_executor.py",
            "src/trading/trade_logger.py",
            "src/backtest/replay_engine.py",
            "src/backtest/trade_simulator.py",
            "src/backtest/metrics.py",
            "src/backtest/data_downloader.py",
        ],
    )
    def test_placeholder_files_exist(self, filepath: str) -> None:
        assert (PROJECT_ROOT / filepath).exists(), f"{filepath} manquant"

    @pytest.mark.parametrize(
        "filepath",
        [
            "src/cli/main.py",
            "src/core/event_bus.py",
            "src/core/state_machine.py",
            "src/core/config.py",
            "src/core/app.py",
            "src/core/state_manager.py",
            "src/core/logging.py",
            "src/core/lock.py",
            "src/core/exceptions.py",
            "src/models/events.py",
            "src/models/trade.py",
            "src/models/config.py",
            "src/models/state.py",
            "src/models/exchange.py",
            "src/exchange/base.py",
            "src/exchange/ccxt_connector.py",
            "src/exchange/rate_limiter.py",
            "src/exchange/order_validator.py",
            "src/strategies/base.py",
            "src/strategies/registry.py",
            "src/capital/base.py",
            "src/capital/registry.py",
            "src/capital/fixed_percent.py",
            "src/indicators/base.py",
            "src/indicators/registry.py",
            "src/indicators/rsi.py",
            "src/trading/trade_executor.py",
            "src/trading/trade_logger.py",
            "src/backtest/replay_engine.py",
            "src/backtest/trade_simulator.py",
            "src/backtest/metrics.py",
            "src/backtest/data_downloader.py",
        ],
    )
    def test_placeholder_files_have_docstring(self, filepath: str) -> None:
        content = (PROJECT_ROOT / filepath).read_text(encoding="utf-8")
        assert '"""' in content, f"{filepath} ne contient pas de docstring"

    def test_conftest_exists(self) -> None:
        assert (PROJECT_ROOT / "tests" / "conftest.py").exists()

    def test_config_directory_exists(self) -> None:
        assert (PROJECT_ROOT / "config").is_dir()

    def test_config_strategies_directory_exists(self) -> None:
        assert (PROJECT_ROOT / "config" / "strategies").is_dir()

    def test_data_directory_exists(self) -> None:
        assert (PROJECT_ROOT / "data").is_dir()

    def test_data_gitkeep_exists(self) -> None:
        assert (PROJECT_ROOT / "data" / ".gitkeep").exists(), "data/.gitkeep manquant — le dossier data/ ne sera pas cloné"


class TestConfigTemplates:
    """Vérifie les templates de configuration (AC #4)."""

    def test_config_example_exists(self) -> None:
        assert (PROJECT_ROOT / "config" / "config.yaml.example").exists()

    def test_config_example_has_exchange_section(self) -> None:
        content = (PROJECT_ROOT / "config" / "config.yaml.example").read_text(
            encoding="utf-8"
        )
        assert "exchange:" in content
        assert "api_key" in content
        assert "api_secret" in content
        assert "testnet" in content

    def test_config_example_has_paths_section(self) -> None:
        content = (PROJECT_ROOT / "config" / "config.yaml.example").read_text(
            encoding="utf-8"
        )
        assert "paths:" in content
        assert "logs" in content
        assert "trades" in content
        assert "state" in content

    def test_config_example_has_defaults_section(self) -> None:
        content = (PROJECT_ROOT / "config" / "config.yaml.example").read_text(
            encoding="utf-8"
        )
        assert "defaults:" in content
        assert "log_level" in content
        assert "risk_percent" in content

    def test_strategy_example_exists(self) -> None:
        assert (
            PROJECT_ROOT / "config" / "strategies" / "example_strategy.yaml"
        ).exists()

    def test_strategy_example_has_required_fields(self) -> None:
        content = (
            PROJECT_ROOT / "config" / "strategies" / "example_strategy.yaml"
        ).read_text(encoding="utf-8")
        for field in ["name:", "pair:", "exchange:", "timeframe:", "leverage:",
                      "conditions:", "capital:"]:
            assert field in content, f"Champ '{field}' manquant dans example_strategy.yaml"


class TestDependencies:
    """Vérifie que les dépendances s'importent correctement (AC #1, #2)."""

    def test_import_click(self) -> None:
        import click
        assert click is not None

    def test_import_ccxt(self) -> None:
        import ccxt
        assert ccxt is not None

    def test_import_yaml(self) -> None:
        import yaml
        assert yaml is not None

    def test_import_pydantic(self) -> None:
        import pydantic
        assert pydantic is not None

    def test_import_loguru(self) -> None:
        from loguru import logger
        assert logger is not None


class TestPyprojectToml:
    """Vérifie la configuration de pyproject.toml (AC #1)."""

    def test_pyproject_exists(self) -> None:
        assert (PROJECT_ROOT / "pyproject.toml").exists()

    def test_pyproject_requires_python_313(self) -> None:
        content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '>=3.13' in content

    def test_pyproject_has_project_name(self) -> None:
        content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "trading-app"' in content

    def test_pyproject_has_script_entry(self) -> None:
        content = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "src.cli.main:cli" in content


class TestGitignore:
    """Vérifie la configuration du .gitignore (AC #5)."""

    def test_gitignore_exists(self) -> None:
        assert (PROJECT_ROOT / ".gitignore").exists()

    def test_gitignore_excludes_config_yaml(self) -> None:
        content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "config/config.yaml" in content

    def test_gitignore_excludes_data(self) -> None:
        content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "data" in content and ("data/" in content or "data/*" in content)

    def test_gitignore_excludes_venv(self) -> None:
        content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert ".venv/" in content
