"""Interface abstraite pour les stratégies de gestion du capital."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal


class BaseCapitalManager(ABC):
    """Interface abstraite pour le calcul de la taille de position.

    Toute stratégie de capital management implémente cette interface.
    Pattern plugin : enregistré via config YAML (mode: "fixed_percent").
    """

    @abstractmethod
    def calculate_position_size(
        self,
        balance: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """Calcule la taille de position en unités de la paire (FR11, FR12).

        Args:
            balance: Capital disponible (balance.free) en USDT
            entry_price: Prix d'entrée estimé (signal_price)
            stop_loss: Prix Stop Loss absolu

        Returns:
            Quantité à trader, arrondie au step_size exchange (ROUND_DOWN)

        Raises:
            ValueError: Si sl_distance == 0 ou quantité résultante == 0
        """
        ...

    def record_trade_result(self, won: bool) -> None:
        """Enregistre le résultat d'un trade pour les stratégies adaptatives (FR44, FR45, FR46).

        Implémentation par défaut : no-op (ignoré pour les stratégies statiques).
        Les stratégies adaptatives (ex: MartingaleCapitalManager) surchargent cette méthode.

        Args:
            won: True si le trade est un gain, False si c'est une perte.
        """

    def get_current_risk_percent(self) -> float | None:
        """Retourne le risk_percent effectif courant, ou None si non disponible.

        Implémentation par défaut : None (les stratégies n'exposant pas leur risque courant).
        Les stratégies concrètes surchargent cette méthode pour exposer le risk_percent utilisé.

        Returns:
            risk_percent courant en pourcentage (ex: 2.0 = 2%), ou None.
        """
        return None
