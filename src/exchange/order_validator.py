"""Validation pre-envoi des ordres (limites, balances, parametres)."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from loguru import logger
from pydantic import BaseModel

from src.core.exceptions import DataValidationError
from src.models.exchange import MarketRules, OrderSide, OrderType

__all__ = ["OrderValidator", "OrderValidationResult"]


class OrderValidationResult(BaseModel):
    """Resultat de la validation pre-envoi d'un ordre."""

    is_valid: bool
    side: OrderSide
    order_type: OrderType
    original_price: Decimal | None
    original_quantity: Decimal
    adjusted_price: Decimal | None
    adjusted_quantity: Decimal
    notional_value: Decimal | None
    errors: list[str]

    def raise_if_invalid(self) -> None:
        """Leve DataValidationError si l'ordre est invalide."""
        if not self.is_valid:
            summary = "; ".join(self.errors)
            raise DataValidationError(
                f"Validation ordre echouee: {summary}",
                context={"errors": self.errors},
            )


class OrderValidator:
    """Validateur pre-envoi des ordres contre les regles exchange."""

    def __init__(self, market_rules: MarketRules) -> None:
        self._market_rules = market_rules

    def round_quantity(self, quantity: Decimal) -> Decimal:
        """Arrondit la quantite au step_size (ROUND_DOWN, conservateur)."""
        return quantity.quantize(self._market_rules.step_size, rounding=ROUND_DOWN)

    def round_price(self, price: Decimal) -> Decimal:
        """Arrondit le prix au tick_size (ROUND_HALF_UP, standard)."""
        return price.quantize(self._market_rules.tick_size, rounding=ROUND_HALF_UP)

    def validate_order(
        self,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None,
        leverage: int | None = None,
    ) -> OrderValidationResult:
        """Valide et ajuste un ordre avant envoi a l'exchange."""
        errors: list[str] = []

        # Validation des entrees negatives
        if quantity <= 0:
            errors.append(f"Quantite doit etre positive (recue: {quantity})")
        if price is not None and price <= 0:
            errors.append(f"Prix doit etre positif (recu: {price})")

        adjusted_quantity = self.round_quantity(quantity) if quantity > 0 else Decimal(0)
        adjusted_price = self.round_price(price) if price is not None and price > 0 else (None if price is None else Decimal(0))

        # Verification quantite arrondie > 0 (seulement si entree positive)
        if quantity > 0 and adjusted_quantity <= 0:
            errors.append(
                f"Quantite trop petite apres arrondi au step_size "
                f"({quantity} -> {adjusted_quantity})"
            )

        # Verification notional (uniquement si prix fourni et quantite arrondie > 0)
        notional_value: Decimal | None = None
        if adjusted_price is not None and adjusted_quantity > 0:
            notional_value = adjusted_quantity * adjusted_price
            if notional_value < self._market_rules.min_notional:
                errors.append(
                    f"Valeur notionnelle {notional_value} < min_notional "
                    f"{self._market_rules.min_notional}"
                )

        # Verification leverage
        if leverage is not None:
            if leverage < 1:
                errors.append(f"Levier doit etre >= 1 (recu: {leverage})")
            elif leverage > self._market_rules.max_leverage:
                errors.append(
                    f"Levier {leverage} depasse le max autorise "
                    f"({self._market_rules.max_leverage})"
                )

        is_valid = len(errors) == 0

        result = OrderValidationResult(
            is_valid=is_valid,
            side=side,
            order_type=order_type,
            original_price=price,
            original_quantity=quantity,
            adjusted_price=adjusted_price,
            adjusted_quantity=adjusted_quantity,
            notional_value=notional_value,
            errors=errors,
        )

        if is_valid:
            logger.debug(
                "Validation ordre OK: {} {} qty={}->{} price={}->{}",
                side,
                order_type,
                quantity,
                adjusted_quantity,
                price,
                adjusted_price,
            )
        else:
            logger.warning(
                "Validation ordre REJETEE: {} {} - erreurs: {}",
                side,
                order_type,
                errors,
            )

        return result
