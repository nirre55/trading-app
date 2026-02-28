"""Tests pour la factory create_capital_manager — Story 7.3."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.capital.factory import create_capital_manager
from src.capital.fixed_percent import FixedPercentCapitalManager
from src.capital.martingale import MartingaleCapitalManager
from src.models.config import CapitalConfig
from src.models.exchange import MarketRules


def make_capital_config(
    mode: str,
    risk_percent: float = 1.0,
    factor: float | None = None,
    max_steps: int | None = None,
) -> CapitalConfig:
    """Fabrique une CapitalConfig pour les tests factory."""
    return CapitalConfig(
        mode=mode,
        risk_percent=risk_percent,
        risk_reward_ratio=2.0,
        factor=factor,
        max_steps=max_steps,
    )


def make_market_rules() -> MarketRules:
    """Fabrique des MarketRules standard pour les tests."""
    return MarketRules(
        step_size=Decimal("0.001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("5"),
        max_leverage=125,
    )


def test_factory_fixed_percent_returns_fixed_manager() -> None:
    """Mode 'fixed_percent' → FixedPercentCapitalManager instancié."""
    config = make_capital_config("fixed_percent")
    market_rules = make_market_rules()

    manager = create_capital_manager(config, market_rules)

    assert isinstance(manager, FixedPercentCapitalManager)


def test_factory_martingale_returns_martingale_manager() -> None:
    """Mode 'martingale' → MartingaleCapitalManager instancié."""
    config = make_capital_config("martingale", factor=2.0, max_steps=3)
    market_rules = make_market_rules()

    manager = create_capital_manager(config, market_rules)

    assert isinstance(manager, MartingaleCapitalManager)


def test_factory_martingale_inverse_returns_martingale_manager() -> None:
    """Mode 'martingale_inverse' → MartingaleCapitalManager instancié."""
    config = make_capital_config("martingale_inverse", factor=1.5, max_steps=2)
    market_rules = make_market_rules()

    manager = create_capital_manager(config, market_rules)

    assert isinstance(manager, MartingaleCapitalManager)


def test_factory_unknown_mode_raises_value_error() -> None:
    """Mode inconnu → ValueError levée avec message explicite."""
    config = make_capital_config("fixed_percent")
    config.mode = "mode_inexistant"  # Bypasse la validation Pydantic
    market_rules = make_market_rules()

    with pytest.raises(ValueError, match="Mode capital non supporté"):
        create_capital_manager(config, market_rules)


def test_factory_fixed_percent_uses_correct_risk() -> None:
    """FixedPercentCapitalManager créé utilise le risk_percent de la config."""
    config = make_capital_config("fixed_percent", risk_percent=2.5)
    market_rules = make_market_rules()

    manager = create_capital_manager(config, market_rules)

    assert isinstance(manager, FixedPercentCapitalManager)
    assert manager.get_current_risk_percent() == 2.5


def test_factory_martingale_initial_risk_equals_base() -> None:
    """MartingaleCapitalManager créé : risk_percent initial = base (avant tout trade)."""
    config = make_capital_config("martingale", risk_percent=1.0, factor=2.0, max_steps=3)
    market_rules = make_market_rules()

    manager = create_capital_manager(config, market_rules)

    assert isinstance(manager, MartingaleCapitalManager)
    assert manager.get_current_risk_percent() == 1.0
