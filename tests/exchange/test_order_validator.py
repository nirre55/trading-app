"""Tests du validateur d'ordres pre-envoi."""

from decimal import Decimal

import pytest

from src.core.exceptions import DataValidationError
from src.exchange.order_validator import OrderValidationResult, OrderValidator
from src.models.exchange import MarketRules, OrderSide, OrderType


@pytest.fixture
def market_rules() -> MarketRules:
    """Regles de marche standard pour les tests."""
    return MarketRules(
        step_size=Decimal("0.0001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("5"),
        max_leverage=125,
    )


@pytest.fixture
def validator(market_rules: MarketRules) -> OrderValidator:
    return OrderValidator(market_rules)


# === Tests d'arrondi de quantite (4 tests) ===


def test_round_quantity_step_size_rounds_down(validator: OrderValidator) -> None:
    """Verifie que la quantite est arrondie vers le bas au step_size."""
    result = validator.round_quantity(Decimal("0.00012345"))
    assert result == Decimal("0.0001")


def test_round_quantity_exact_step(validator: OrderValidator) -> None:
    """Verifie qu'une quantite deja au step_size ne change pas."""
    result = validator.round_quantity(Decimal("0.0003"))
    assert result == Decimal("0.0003")


def test_round_quantity_very_small(validator: OrderValidator) -> None:
    """Verifie qu'une quantite trop petite est arrondie a zero."""
    result = validator.round_quantity(Decimal("0.00001"))
    assert result == Decimal("0.0000")


def test_round_quantity_large(validator: OrderValidator) -> None:
    """Verifie l'arrondi d'une grande quantite."""
    rules = MarketRules(
        step_size=Decimal("0.001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("5"),
        max_leverage=125,
    )
    v = OrderValidator(rules)
    result = v.round_quantity(Decimal("1.23456789"))
    assert result == Decimal("1.234")


# === Tests d'arrondi de prix (3 tests) ===


def test_round_price_tick_size_rounds_half_up(validator: OrderValidator) -> None:
    """Verifie que le prix est arrondi au tick_size avec ROUND_HALF_UP."""
    result = validator.round_price(Decimal("45123.456"))
    assert result == Decimal("45123.46")


def test_round_price_exact_tick(validator: OrderValidator) -> None:
    """Verifie qu'un prix deja au tick_size ne change pas."""
    result = validator.round_price(Decimal("45123.45"))
    assert result == Decimal("45123.45")


def test_round_price_rounds_up_at_midpoint(validator: OrderValidator) -> None:
    """Verifie que ROUND_HALF_UP arrondit vers le haut au point median."""
    result = validator.round_price(Decimal("45123.455"))
    assert result == Decimal("45123.46")


# === Tests de validation complete (7 tests) ===


def test_validate_order_valid_limit_order(validator: OrderValidator) -> None:
    """Verifie qu'un ordre limit valide passe la validation."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        price=Decimal("45000.123"),
        leverage=10,
    )
    assert result.is_valid is True
    assert result.adjusted_quantity == Decimal("0.5000")
    assert result.adjusted_price == Decimal("45000.12")
    assert result.errors == []


def test_validate_order_valid_market_order(validator: OrderValidator) -> None:
    """Verifie qu'un ordre market (price=None) passe sans verification notionnelle."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.5"),
        price=None,
    )
    assert result.is_valid is True
    assert result.adjusted_price is None
    assert result.notional_value is None
    assert result.errors == []


def test_validate_order_quantity_too_small(validator: OrderValidator) -> None:
    """Verifie qu'une quantite arrondie a zero est rejetee."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00001"),
        price=Decimal("45000.00"),
    )
    assert result.is_valid is False
    assert any("trop petite" in e for e in result.errors)


def test_validate_order_below_min_notional(validator: OrderValidator) -> None:
    """Verifie le rejet quand la valeur notionnelle est sous le min_notional."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0001"),
        price=Decimal("100.00"),
    )
    assert result.is_valid is False
    assert any("min_notional" in e for e in result.errors)


def test_validate_order_leverage_exceeds_max(validator: OrderValidator) -> None:
    """Verifie le rejet quand le levier depasse le max_leverage."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        price=Decimal("45000.00"),
        leverage=200,
    )
    assert result.is_valid is False
    assert any("levier" in e.lower() for e in result.errors)


def test_validate_order_multiple_errors(validator: OrderValidator) -> None:
    """Verifie que plusieurs erreurs sont collectees simultanement."""
    # Quantite valide mais notionnel < min_notional (0.0001 * 100 = 0.01 < 5) + leverage depasse
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0001"),
        price=Decimal("100.00"),
        leverage=200,
    )
    assert result.is_valid is False
    assert len(result.errors) >= 2
    assert any("min_notional" in e for e in result.errors)
    assert any("levier" in e.lower() for e in result.errors)


def test_validate_order_preserves_side_and_type(validator: OrderValidator) -> None:
    """Verifie que side et order_type sont correctement propages dans le resultat."""
    result = validator.validate_order(
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        price=Decimal("45000.00"),
    )
    assert result.is_valid is True
    assert result.side == OrderSide.SELL
    assert result.order_type == OrderType.LIMIT


# === Tests du modele OrderValidationResult (2 tests) ===


def test_validation_result_raise_if_invalid_raises() -> None:
    """Verifie que raise_if_invalid() leve DataValidationError si is_valid=False."""
    result = OrderValidationResult(
        is_valid=False,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        original_price=Decimal("100.00"),
        original_quantity=Decimal("0.001"),
        adjusted_price=Decimal("100.00"),
        adjusted_quantity=Decimal("0.001"),
        notional_value=Decimal("0.1"),
        errors=["Valeur notionnelle trop faible"],
    )
    with pytest.raises(DataValidationError):
        result.raise_if_invalid()


def test_validation_result_raise_if_valid_noop() -> None:
    """Verifie que raise_if_invalid() ne leve rien si is_valid=True."""
    result = OrderValidationResult(
        is_valid=True,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        original_price=Decimal("45000.00"),
        original_quantity=Decimal("0.5"),
        adjusted_price=Decimal("45000.00"),
        adjusted_quantity=Decimal("0.5"),
        notional_value=Decimal("22500.00"),
        errors=[],
    )
    result.raise_if_invalid()  # Ne doit pas lever d'exception


# === Tests de validation des entrees (3 tests) ===


def test_validate_order_negative_quantity_rejected(validator: OrderValidator) -> None:
    """Verifie qu'une quantite negative est rejetee avec un message clair."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("-1"),
        price=Decimal("45000.00"),
    )
    assert result.is_valid is False
    assert any("positive" in e for e in result.errors)


def test_validate_order_negative_price_rejected(validator: OrderValidator) -> None:
    """Verifie qu'un prix negatif est rejete avec un message clair."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        price=Decimal("-100"),
    )
    assert result.is_valid is False
    assert any("positif" in e.lower() for e in result.errors)


def test_validate_order_zero_leverage_rejected(validator: OrderValidator) -> None:
    """Verifie qu'un levier de 0 est rejete."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.5"),
        price=Decimal("45000.00"),
        leverage=0,
    )
    assert result.is_valid is False
    assert any("levier" in e.lower() for e in result.errors)


def test_validate_order_quantity_zero_no_redundant_notional_error(validator: OrderValidator) -> None:
    """Verifie que quantite arrondie a zero ne produit pas d'erreur notionnelle redondante."""
    result = validator.validate_order(
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00001"),
        price=Decimal("45000.00"),
    )
    assert result.is_valid is False
    assert len(result.errors) == 1
    assert "trop petite" in result.errors[0]
