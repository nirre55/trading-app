"""Tests unitaires pour BaseCapitalManager, FixedPercentCapitalManager et round_quantity()."""

from decimal import Decimal

import pytest

from src.capital.base import BaseCapitalManager
from src.capital.fixed_percent import FixedPercentCapitalManager
from src.exchange.order_validator import OrderValidator
from src.models.exchange import MarketRules


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_market_rules(
    step_size: str = "0.001",
    tick_size: str = "0.1",
    min_notional: str = "10",
    max_leverage: int = 10,
) -> MarketRules:
    return MarketRules(
        step_size=Decimal(step_size),
        tick_size=Decimal(tick_size),
        min_notional=Decimal(min_notional),
        max_leverage=max_leverage,
    )


# ── Tests BaseCapitalManager (abstractmethod) ─────────────────────────────────


def test_base_capital_manager_cannot_be_instantiated() -> None:
    """5.1 : BaseCapitalManager est abstraite — instanciation directe impossible."""
    with pytest.raises(TypeError):
        BaseCapitalManager()  # type: ignore[abstract]


def test_base_capital_manager_concrete_must_implement_method() -> None:
    """5.1 : Classe concrète sans calculate_position_size → TypeError à l'instanciation."""

    class IncompleteManager(BaseCapitalManager):
        pass  # N'implémente pas l'abstractmethod

    with pytest.raises(TypeError):
        IncompleteManager()  # type: ignore[abstract]


# ── Tests FixedPercentCapitalManager ─────────────────────────────────────────


def test_calculate_position_size_long_standard() -> None:
    """5.2 : LONG — balance=10000, risk=1%, entry=50000, sl=49000 → qty=0.1."""
    # dist = 50000 - 49000 = 1000, risk_amount = 10000 × 0.01 = 100, raw = 100/1000 = 0.1
    manager = FixedPercentCapitalManager(
        risk_percent=1.0, market_rules=make_market_rules(step_size="0.001")
    )
    result = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    assert result == Decimal("0.100")


def test_calculate_position_size_short_standard() -> None:
    """5.3 : SHORT — balance=10000, risk=1%, entry=50000, sl=51000 → qty=0.1."""
    # dist = abs(50000 - 51000) = 1000, risk_amount = 100, raw = 0.1
    manager = FixedPercentCapitalManager(
        risk_percent=1.0, market_rules=make_market_rules(step_size="0.001")
    )
    result = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("51000"),
    )
    assert result == Decimal("0.100")


def test_calculate_position_size_rounds_down_step_001() -> None:
    """5.4 : step_size=0.001, raw≈0.12345... → 0.123 (ROUND_DOWN)."""
    # balance=10000, risk=1% → risk_amount=100, dist=810 → raw=100/810≈0.123456...
    manager = FixedPercentCapitalManager(
        risk_percent=1.0, market_rules=make_market_rules(step_size="0.001")
    )
    result = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49190"),  # dist = 810
    )
    # risk_amount = 100, raw = 100/810 = 0.12345679... → step=0.001, ROUND_DOWN → 0.123
    assert result == Decimal("0.123")


def test_calculate_position_size_rounds_down_step_01() -> None:
    """5.5 : step_size=0.01, raw≈0.12563... → 0.12 (ROUND_DOWN)."""
    # balance=10000, risk=1% → risk_amount=100, dist=796 → raw=100/796≈0.12563...
    manager = FixedPercentCapitalManager(
        risk_percent=1.0, market_rules=make_market_rules(step_size="0.01")
    )
    result = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49204"),  # dist = 796
    )
    # raw ≈ 0.12563 → step=0.01, ROUND_DOWN → 0.12
    assert result == Decimal("0.12")


def test_risk_percent_zero_raises_value_error() -> None:
    """risk_percent=0 → ValueError dans __init__ (risque nul interdit)."""
    with pytest.raises(ValueError, match="risk_percent doit être > 0"):
        FixedPercentCapitalManager(
            risk_percent=0.0,
            market_rules=make_market_rules(),
        )


def test_risk_percent_negative_raises_value_error() -> None:
    """risk_percent négatif → ValueError dans __init__ (risque négatif invalide)."""
    with pytest.raises(ValueError, match="risk_percent doit être > 0"):
        FixedPercentCapitalManager(
            risk_percent=-1.0,
            market_rules=make_market_rules(),
        )


def test_calculate_position_size_sl_distance_zero_raises() -> None:
    """5.6 : entry_price == stop_loss → ValueError (distance SL nulle)."""
    manager = FixedPercentCapitalManager(
        risk_percent=1.0, market_rules=make_market_rules()
    )
    with pytest.raises(ValueError, match="Distance SL invalide"):
        manager.calculate_position_size(
            balance=Decimal("10000"),
            entry_price=Decimal("50000"),
            stop_loss=Decimal("50000"),  # même prix → distance=0
        )


def test_calculate_position_size_quantity_zero_after_rounding_raises() -> None:
    """5.7 : balance très faible + grand step_size → qty arrondie = 0 → ValueError."""
    # step_size=1 (très grand), balance=1 USDT, risk=1% → risk_amount=0.01 USDT
    # dist=1000 → raw=0.01/1000=0.00001 → step=1, ROUND_DOWN → 0 → ValueError
    manager = FixedPercentCapitalManager(
        risk_percent=1.0,
        market_rules=make_market_rules(step_size="1"),
    )
    with pytest.raises(ValueError, match="Quantité calculée nulle"):
        manager.calculate_position_size(
            balance=Decimal("1"),
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),  # dist=1000
        )


def test_calculate_position_size_decimal_conversion_no_drift() -> None:
    """5.8 : risk_percent=1.5 → conversion exacte via Decimal(str()) sans dérive flottante."""
    manager = FixedPercentCapitalManager(
        risk_percent=1.5,
        market_rules=make_market_rules(step_size="0.001"),
    )
    # balance=10000, risk=1.5% → risk_amount = 150 USDT, dist=1000 → raw=0.150
    result = manager.calculate_position_size(
        balance=Decimal("10000"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
    )
    # risk_amount = 10000 × 0.015 = 150 USDT, raw = 150/1000 = 0.15 → step=0.001 → 0.150
    assert result == Decimal("0.150")


# ── Tests round_quantity() dans OrderValidator ────────────────────────────────


def test_round_quantity_step_001_rounds_down() -> None:
    """5.9 : OrderValidator.round_quantity, step=0.001, qty=0.1234567 → 0.123 (ROUND_DOWN)."""
    validator = OrderValidator(make_market_rules(step_size="0.001"))
    result = validator.round_quantity(Decimal("0.1234567"))
    assert result == Decimal("0.123")


def test_round_quantity_step_01_rounds_down() -> None:
    """5.9 : OrderValidator.round_quantity, step=0.01, qty=0.1299 → 0.12 (ROUND_DOWN)."""
    validator = OrderValidator(make_market_rules(step_size="0.01"))
    result = validator.round_quantity(Decimal("0.1299"))
    assert result == Decimal("0.12")
