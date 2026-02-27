"""Stratégie de capital adaptative martingale et martingale inversée."""

from __future__ import annotations

from decimal import Decimal

from loguru import logger

from src.capital.base import BaseCapitalManager
from src.exchange.order_validator import OrderValidator
from src.models.config import CapitalConfig
from src.models.exchange import MarketRules

__all__ = ["MartingaleCapitalManager"]

_MARTINGALE_MODE = "martingale"
_MARTINGALE_INVERSE_MODE = "martingale_inverse"


class MartingaleCapitalManager(BaseCapitalManager):
    """Position sizing adaptatif : martingale ou martingale inversée (FR44, FR45, FR46).

    Martingale : multiplie le risk_percent par `factor` après chaque perte ;
                 réinitialise après un gain.
    Martingale inversée : multiplie après chaque gain ; réinitialise après une perte.
    Protection : le multiplicateur est plafonné à `factor^max_steps` (AC2, AC6).
    """

    def __init__(self, config: CapitalConfig, market_rules: MarketRules) -> None:
        if config.mode not in {_MARTINGALE_MODE, _MARTINGALE_INVERSE_MODE}:
            raise ValueError(
                f"Mode non supporté par MartingaleCapitalManager: {config.mode!r}. "
                f"Modes valides : {_MARTINGALE_MODE!r}, {_MARTINGALE_INVERSE_MODE!r}"
            )
        if config.risk_percent <= 0:
            raise ValueError(
                f"risk_percent doit être > 0, reçu: {config.risk_percent}. "
                "Exemple valide : 1.0 = 1% du capital risqué par trade."
            )
        self._config = config
        self._market_rules = market_rules
        self._validator = OrderValidator(market_rules)
        self._consecutive_count: int = 0

    def _effective_risk_percent(self) -> float:
        """Retourne le risk_percent effectif plafonné à max_steps (FR44, FR45, FR46)."""
        factor = self._config.factor or 1.0
        if self._config.max_steps is not None:
            steps = min(self._consecutive_count, self._config.max_steps)
        else:
            steps = self._consecutive_count
        return self._config.risk_percent * (factor**steps)

    def record_trade_result(self, won: bool) -> None:
        """Enregistre le résultat d'un trade et met à jour l'état de la séquence.

        Args:
            won: True si le trade est un gain, False si c'est une perte.
        """
        trigger = (not won) if self._config.mode == _MARTINGALE_MODE else won
        if trigger:
            if self._config.max_steps is None or self._consecutive_count < self._config.max_steps:
                self._consecutive_count += 1
                if (
                    self._config.max_steps is not None
                    and self._consecutive_count == self._config.max_steps
                ):
                    logger.warning("[WARN] max_steps atteint — risk_percent plafonné")
        else:
            self._consecutive_count = 0

    def calculate_position_size(
        self,
        balance: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """Calcule la taille de position avec le risk_percent adaptatif (FR44, FR45, FR46).

        Args:
            balance: Capital disponible en USDT.
            entry_price: Prix d'entrée estimé.
            stop_loss: Prix Stop Loss absolu.

        Returns:
            Quantité à trader, arrondie au step_size (ROUND_DOWN).

        Raises:
            ValueError: Si sl_distance == 0 ou quantité résultante == 0.
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            raise ValueError(
                f"Distance SL invalide : entry_price ({entry_price}) == stop_loss ({stop_loss})"
            )

        effective_risk = self._effective_risk_percent()
        risk_amount = balance * Decimal(str(effective_risk)) / Decimal("100")
        raw_quantity = risk_amount / sl_distance

        quantity = self._validator.round_quantity(raw_quantity)

        logger.debug(
            "Martingale sizing — mode={} consecutive={} effective_risk={}% "
            "balance={} sl_distance={} risk_amount={} qty={}",
            self._config.mode,
            self._consecutive_count,
            effective_risk,
            balance,
            sl_distance,
            risk_amount,
            quantity,
        )

        if quantity <= 0:
            raise ValueError(
                f"Quantité calculée nulle après arrondi — balance={balance} "
                f"effective_risk={effective_risk}% sl_distance={sl_distance}. "
                "Augmentez le capital ou élargissez le SL."
            )

        return quantity
