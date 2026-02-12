"""Tests pour le module de chargement et validation de la configuration."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from src.core.config import (
    load_app_config,
    load_strategy_by_name,
    load_strategy_config,
    load_yaml_file,
)
from src.core.exceptions import ConfigError
from src.models.config import AppConfig, StrategyConfig

# === Fixtures ===


@pytest.fixture
def valid_app_config_yaml(tmp_path: Path) -> Path:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
exchange:
  name: "binance"
  api_key: "test_key_123"
  api_secret: "test_secret_456"
  testnet: true
paths:
  logs: "data/logs"
  trades: "data/trades"
  state: "data/state.json"
defaults:
  log_level: "INFO"
  risk_percent: 1.0
""",
        encoding="utf-8",
    )
    return config_file


@pytest.fixture
def valid_strategy_yaml(tmp_path: Path) -> Path:
    strategy_file = tmp_path / "test_strategy.yaml"
    strategy_file.write_text(
        """
name: "test_strategy"
pair: "BTC/USDT"
exchange: "binance"
timeframe: "1h"
leverage: 10
conditions:
  - type: "rsi_oversold"
    params:
      period: 14
      threshold: 30
    max_gap_candles: 3
  - type: "price_above_ma"
    params:
      period: 50
timeout_candles: 10
capital:
  mode: "fixed_percent"
  risk_percent: 1.0
  risk_reward_ratio: 2.0
""",
        encoding="utf-8",
    )
    return strategy_file


# === Tests load_yaml_file ===


class TestLoadYamlFile:
    def test_load_yaml_file_valid(self, valid_app_config_yaml: Path) -> None:
        result = load_yaml_file(valid_app_config_yaml)
        assert isinstance(result, dict)
        assert result["exchange"]["name"] == "binance"

    def test_load_yaml_file_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(ConfigError, match="missing.yaml"):
            load_yaml_file(missing)

    def test_load_yaml_file_invalid_yaml(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{{broken yaml", encoding="utf-8")
        with pytest.raises(ConfigError, match="parsing YAML"):
            load_yaml_file(bad_file)

    def test_load_yaml_file_empty_file(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(ConfigError, match="vide"):
            load_yaml_file(empty_file)

    def test_load_yaml_file_non_dict_content(self, tmp_path: Path) -> None:
        list_file = tmp_path / "list.yaml"
        list_file.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="mapping"):
            load_yaml_file(list_file)


# === Tests load_app_config ===


class TestLoadAppConfig:
    def test_load_app_config_valid(self, valid_app_config_yaml: Path) -> None:
        config = load_app_config(valid_app_config_yaml)
        assert isinstance(config, AppConfig)
        assert config.exchange.name == "binance"
        assert config.paths.logs == "data/logs"
        assert config.defaults.log_level == "INFO"

    def test_load_app_config_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "config.yaml"
        with pytest.raises(ConfigError, match="introuvable"):
            load_app_config(missing)

    def test_load_app_config_invalid_yaml(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "config.yaml"
        bad_file.write_text("{{{broken", encoding="utf-8")
        with pytest.raises(ConfigError, match="parsing YAML"):
            load_app_config(bad_file)

    def test_load_app_config_missing_required_fields(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
paths:
  logs: "data/logs"
  trades: "data/trades"
  state: "data/state.json"
defaults:
  log_level: "INFO"
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="exchange"):
            load_app_config(config_file)

    def test_load_app_config_invalid_types(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
exchange:
  name: "binance"
  api_key: "key"
  api_secret: "secret"
  testnet: true
paths:
  logs: "data/logs"
  trades: "data/trades"
  state: "data/state.json"
defaults:
  log_level: "INFO"
  risk_percent: "not_a_float"
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="Validation"):
            load_app_config(config_file)


# === Tests load_strategy_config ===


class TestLoadStrategyConfig:
    def test_load_strategy_config_valid(self, valid_strategy_yaml: Path) -> None:
        strategy = load_strategy_config(valid_strategy_yaml)
        assert isinstance(strategy, StrategyConfig)
        assert strategy.name == "test_strategy"
        assert strategy.pair == "BTC/USDT"
        assert strategy.leverage == 10
        assert len(strategy.conditions) == 2

    def test_load_strategy_config_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing_strategy.yaml"
        with pytest.raises(ConfigError, match="introuvable"):
            load_strategy_config(missing)

    def test_load_strategy_config_invalid_fields(self, tmp_path: Path) -> None:
        strategy_file = tmp_path / "bad_strategy.yaml"
        strategy_file.write_text(
            """
name: "bad_strategy"
pair: "BTC/USDT"
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="Validation"):
            load_strategy_config(strategy_file)


# === Tests load_strategy_by_name ===


class TestLoadStrategyByName:
    def test_load_strategy_by_name_valid(self, tmp_path: Path) -> None:
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        strategy_file = strategies_dir / "my_strategy.yaml"
        strategy_file.write_text(
            """
name: "my_strategy"
pair: "ETH/USDT"
exchange: "binance"
timeframe: "4h"
leverage: 5
conditions:
  - type: "rsi_oversold"
    params:
      period: 14
      threshold: 30
timeout_candles: 8
capital:
  mode: "fixed_percent"
  risk_percent: 2.0
  risk_reward_ratio: 1.5
""",
            encoding="utf-8",
        )
        strategy = load_strategy_by_name("my_strategy", strategies_dir)
        assert isinstance(strategy, StrategyConfig)
        assert strategy.name == "my_strategy"
        assert strategy.pair == "ETH/USDT"

    def test_load_strategy_by_name_not_found(self, tmp_path: Path) -> None:
        strategies_dir = tmp_path / "strategies"
        strategies_dir.mkdir()
        with pytest.raises(ConfigError, match="inexistant"):
            load_strategy_by_name("inexistant", strategies_dir)


# === Tests sécurité clés API ===


class TestApiKeySecurity:
    def test_api_keys_stored_as_secret_str(self, valid_app_config_yaml: Path) -> None:
        config = load_app_config(valid_app_config_yaml)
        assert isinstance(config.exchange.api_key, SecretStr)
        assert isinstance(config.exchange.api_secret, SecretStr)
        assert str(config.exchange.api_key) == "**********"
        assert str(config.exchange.api_secret) == "**********"

    def test_api_keys_not_in_repr(self, valid_app_config_yaml: Path) -> None:
        config = load_app_config(valid_app_config_yaml)
        config_repr = repr(config)
        assert "test_key_123" not in config_repr
        assert "test_secret_456" not in config_repr
