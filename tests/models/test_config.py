"""Tests pour les modèles de configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from src.models.config import (
    AppConfig,
    CapitalConfig,
    ConditionConfig,
    DefaultsConfig,
    ExchangeConfig,
    PathsConfig,
    StrategyConfig,
)


def _valid_exchange_config() -> dict:
    return {
        "name": "binance",
        "api_key": "test_key",
        "api_secret": "test_secret",
    }


def _valid_paths_config() -> dict:
    return {"logs": "data/logs", "trades": "data/trades", "state": "data/state"}


def _valid_app_config_dict() -> dict:
    return {
        "exchange": _valid_exchange_config(),
        "paths": _valid_paths_config(),
        "defaults": {},
    }


def _valid_strategy_config_dict() -> dict:
    return {
        "name": "ma_strategie",
        "pair": "BTC/USDT",
        "exchange": "binance",
        "timeframe": "1h",
        "leverage": 5,
        "conditions": [
            {"type": "rsi_oversold", "params": {"period": 14, "threshold": 30}}
        ],
        "timeout_candles": 10,
        "capital": {
            "mode": "fixed_percent",
            "risk_percent": 1.0,
            "risk_reward_ratio": 2.0,
        },
    }


class TestExchangeConfig:
    """Tests pour ExchangeConfig."""

    def test_instanciation_valide(self):
        config = ExchangeConfig(**_valid_exchange_config())
        assert config.name == "binance"
        assert isinstance(config.api_key, SecretStr)
        assert config.api_key.get_secret_value() == "test_key"

    def test_secret_str_masque_repr(self):
        config = ExchangeConfig(**_valid_exchange_config())
        assert "test_key" not in repr(config)
        assert "test_secret" not in repr(config)

    def test_testnet_par_defaut_true(self):
        config = ExchangeConfig(**_valid_exchange_config())
        assert config.testnet is True

    def test_testnet_explicit_false(self):
        data = {**_valid_exchange_config(), "testnet": False}
        config = ExchangeConfig(**data)
        assert config.testnet is False

    def test_champ_manquant_raise_validation_error(self):
        with pytest.raises(ValidationError):
            ExchangeConfig(name="binance", api_key="key")  # type: ignore


class TestPathsConfig:
    """Tests pour PathsConfig."""

    def test_instanciation_valide(self):
        config = PathsConfig(**_valid_paths_config())
        assert config.logs == "data/logs"

    def test_champ_manquant_raise_validation_error(self):
        with pytest.raises(ValidationError):
            PathsConfig(logs="logs")  # type: ignore


class TestDefaultsConfig:
    """Tests pour DefaultsConfig."""

    def test_valeurs_par_defaut(self):
        config = DefaultsConfig()
        assert config.log_level == "INFO"
        assert config.risk_percent == 1.0

    def test_override_valeurs(self):
        config = DefaultsConfig(log_level="DEBUG", risk_percent=2.5)
        assert config.log_level == "DEBUG"
        assert config.risk_percent == 2.5


class TestAppConfig:
    """Tests pour AppConfig."""

    def test_instanciation_valide(self):
        config = AppConfig(**_valid_app_config_dict())
        assert config.exchange.name == "binance"
        assert config.paths.logs == "data/logs"
        assert config.defaults.log_level == "INFO"

    def test_champ_manquant_raise_validation_error(self):
        with pytest.raises(ValidationError):
            AppConfig(exchange=_valid_exchange_config())  # type: ignore

    def test_type_invalide_raise_validation_error(self):
        data = _valid_app_config_dict()
        data["exchange"] = "pas un dict"
        with pytest.raises(ValidationError):
            AppConfig(**data)


class TestConditionConfig:
    """Tests pour ConditionConfig."""

    def test_instanciation_valide(self):
        config = ConditionConfig(
            type="rsi_oversold", params={"period": 14, "threshold": 30}
        )
        assert config.type == "rsi_oversold"
        assert config.params["period"] == 14

    def test_max_gap_candles_optionnel(self):
        config = ConditionConfig(type="test", params={})
        assert config.max_gap_candles is None

    def test_max_gap_candles_explicite(self):
        config = ConditionConfig(type="test", params={}, max_gap_candles=5)
        assert config.max_gap_candles == 5


class TestCapitalConfig:
    """Tests pour CapitalConfig."""

    def test_instanciation_valide(self):
        config = CapitalConfig(
            mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=2.0
        )
        assert config.mode == "fixed_percent"
        assert config.risk_percent == 1.0
        assert config.risk_reward_ratio == 2.0


class TestStrategyConfig:
    """Tests pour StrategyConfig."""

    def test_instanciation_valide(self):
        config = StrategyConfig(**_valid_strategy_config_dict())
        assert config.name == "ma_strategie"
        assert config.pair == "BTC/USDT"
        assert config.leverage == 5
        assert len(config.conditions) == 1

    def test_champ_manquant_raise_validation_error(self):
        with pytest.raises(ValidationError):
            StrategyConfig(name="test", pair="BTC/USDT")  # type: ignore

    def test_type_invalide_leverage_raise_validation_error(self):
        data = _valid_strategy_config_dict()
        data["leverage"] = "pas_un_int"
        with pytest.raises(ValidationError):
            StrategyConfig(**data)

    def test_serialisation_json(self):
        config = StrategyConfig(**_valid_strategy_config_dict())
        json_str = config.model_dump_json()
        assert "ma_strategie" in json_str
        assert "BTC/USDT" in json_str
