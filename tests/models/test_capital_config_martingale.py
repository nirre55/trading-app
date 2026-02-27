"""Tests pour CapitalConfig — modes martingale et martingale_inverse (Story 7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.config import load_strategy_config
from src.core.exceptions import ConfigError
from src.models.config import CapitalConfig


def _strategy_yaml(capital_block: str) -> str:
    return f"""
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
timeout_candles: 10
capital:
{capital_block}
"""


# === AC 1 : Config martingale valide ===


class TestCapitalConfigMartingaleValide:
    def test_martingale_instanciation_valide(self) -> None:
        config = CapitalConfig(
            mode="martingale",
            risk_percent=1.0,
            risk_reward_ratio=2.0,
            factor=2.0,
            max_steps=3,
        )
        assert config.mode == "martingale"
        assert config.factor == 2.0
        assert config.max_steps == 3

    def test_martingale_expose_mode_factor_max_steps(self) -> None:
        config = CapitalConfig(
            mode="martingale",
            risk_percent=1.0,
            risk_reward_ratio=2.0,
            factor=2.0,
            max_steps=3,
        )
        assert hasattr(config, "mode")
        assert hasattr(config, "factor")
        assert hasattr(config, "max_steps")

    def test_martingale_via_loader(self, tmp_path: Path) -> None:
        strategy_file = tmp_path / "strat.yaml"
        strategy_file.write_text(
            _strategy_yaml(
                "  mode: \"martingale\"\n"
                "  risk_percent: 1.0\n"
                "  risk_reward_ratio: 2.0\n"
                "  factor: 2.0\n"
                "  max_steps: 3"
            ),
            encoding="utf-8",
        )
        strategy = load_strategy_config(strategy_file)
        assert strategy.capital.mode == "martingale"
        assert strategy.capital.factor == 2.0
        assert strategy.capital.max_steps == 3


# === AC 2 : Config martingale inversée valide ===


class TestCapitalConfigMartingaleInverseValide:
    def test_martingale_inverse_instanciation_valide(self) -> None:
        config = CapitalConfig(
            mode="martingale_inverse",
            risk_percent=1.0,
            risk_reward_ratio=2.0,
            factor=1.5,
            max_steps=2,
        )
        assert config.mode == "martingale_inverse"
        assert config.factor == 1.5
        assert config.max_steps == 2

    def test_martingale_inverse_via_loader(self, tmp_path: Path) -> None:
        strategy_file = tmp_path / "strat_inv.yaml"
        strategy_file.write_text(
            _strategy_yaml(
                "  mode: \"martingale_inverse\"\n"
                "  risk_percent: 1.0\n"
                "  risk_reward_ratio: 2.0\n"
                "  factor: 1.5\n"
                "  max_steps: 2"
            ),
            encoding="utf-8",
        )
        strategy = load_strategy_config(strategy_file)
        assert strategy.capital.mode == "martingale_inverse"
        assert strategy.capital.factor == 1.5
        assert strategy.capital.max_steps == 2


# === AC 3 : Rétrocompatibilité fixed_percent ===


class TestCapitalConfigRetrocompat:
    def test_fixed_percent_sans_factor_valide(self) -> None:
        config = CapitalConfig(
            mode="fixed_percent",
            risk_percent=1.0,
            risk_reward_ratio=2.0,
        )
        assert config.mode == "fixed_percent"
        assert config.factor is None
        assert config.max_steps is None

    def test_fixed_percent_via_loader(self, tmp_path: Path) -> None:
        strategy_file = tmp_path / "strat_fixed.yaml"
        strategy_file.write_text(
            _strategy_yaml(
                "  mode: \"fixed_percent\"\n"
                "  risk_percent: 1.0\n"
                "  risk_reward_ratio: 2.0"
            ),
            encoding="utf-8",
        )
        strategy = load_strategy_config(strategy_file)
        assert strategy.capital.mode == "fixed_percent"
        assert strategy.capital.factor is None


# === AC 4 : Champ factor manquant → ConfigError ===


class TestCapitalConfigFactorManquant:
    def test_martingale_sans_factor_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="factor"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
            )

    def test_martingale_inverse_sans_factor_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="factor"):
            CapitalConfig(
                mode="martingale_inverse",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
            )

    def test_martingale_sans_factor_via_loader_raise_config_error(
        self, tmp_path: Path
    ) -> None:
        strategy_file = tmp_path / "no_factor.yaml"
        strategy_file.write_text(
            _strategy_yaml(
                "  mode: \"martingale\"\n"
                "  risk_percent: 1.0\n"
                "  risk_reward_ratio: 2.0"
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load_strategy_config(strategy_file)


# === AC 5 : Valeurs invalides → ConfigError ===


class TestCapitalConfigValeursInvalides:
    def test_factor_zero_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=0,
                max_steps=3,
            )

    def test_factor_negatif_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=-1.0,
                max_steps=3,
            )

    def test_max_steps_zero_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=2.0,
                max_steps=0,
            )

    def test_max_steps_negatif_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=2.0,
                max_steps=-1,
            )

    def test_factor_zero_via_loader_raise_config_error(self, tmp_path: Path) -> None:
        strategy_file = tmp_path / "factor_zero.yaml"
        strategy_file.write_text(
            _strategy_yaml(
                "  mode: \"martingale\"\n"
                "  risk_percent: 1.0\n"
                "  risk_reward_ratio: 2.0\n"
                "  factor: 0\n"
                "  max_steps: 3"
            ),
            encoding="utf-8",
        )
        with pytest.raises(ConfigError):
            load_strategy_config(strategy_file)

    def test_fixed_percent_avec_factor_invalide_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="strictement positif"):
            CapitalConfig(
                mode="fixed_percent",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=0,
            )

    def test_factor_nan_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="fini strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=float("nan"),
                max_steps=3,
            )

    def test_factor_inf_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="fini strictement positif"):
            CapitalConfig(
                mode="martingale",
                risk_percent=1.0,
                risk_reward_ratio=2.0,
                factor=float("inf"),
                max_steps=3,
            )
