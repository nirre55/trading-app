"""Stratégie de capital à pourcentage fixe du solde."""

from __future__ import annotations

from decimal import Decimal

from loguru import logger

from src.capital.base import BaseCapitalManager
from src.exchange.order_validator import OrderValidator
from src.models.exchange import MarketRules


class FixedPercentCapitalManager(BaseCapitalManager):
    """Position sizing basé sur un % fixe du capital risqué par trade (FR11, FR12, FR27).

    Formule : quantity = (balance × risk_percent / 100) / sl_distance
    Exemple : balance=10000 USDT, risk_percent=1%, entry=50000, sl=49000
              → risk_amount = 100 USDT, sl_distance = 1000 → qty = 0.1 BTC
    """

    def __init__(self, risk_percent: float, market_rules: MarketRules) -> None:
        if risk_percent <= 0:
            raise ValueError(
                f"risk_percent doit être > 0, reçu: {risk_percent}. "
                "Exemple valide : 1.0 = 1% du capital risqué par trade."
            )
        self._risk_percent = risk_percent
        self._market_rules = market_rules
        self._validator = OrderValidator(market_rules)

    def get_current_risk_percent(self) -> float | None:
        """Retourne le risk_percent fixe configuré."""
        return self._risk_percent

    def calculate_position_size(
        self,
        balance: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """Calcule la quantité à trader selon le % de risque et la distance SL (FR11, FR12, FR27)."""
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            raise ValueError(
                f"Distance SL invalide : entry_price ({entry_price}) == stop_loss ({stop_loss})"
            )

        risk_amount = balance * Decimal(str(self._risk_percent)) / Decimal("100")
        raw_quantity = risk_amount / sl_distance

        quantity = self._validator.round_quantity(raw_quantity)

        logger.debug(
            "Position sizing — balance={} risk_percent={}% sl_distance={} "
            "risk_amount={} raw_qty={} qty_arrondie={}",
            balance,
            self._risk_percent,
            sl_distance,
            risk_amount,
            raw_quantity,
            quantity,
        )

        if quantity <= 0:
            raise ValueError(
                f"Quantité calculée nulle après arrondi — balance={balance} "
                f"risk_percent={self._risk_percent}% sl_distance={sl_distance}. "
                "Augmentez le capital ou élargissez le SL."
            )

        return quantity
