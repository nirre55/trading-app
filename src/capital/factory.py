"""Factory pour l'instanciation du capital manager selon le mode configuré."""

from __future__ import annotations

from src.capital.base import BaseCapitalManager
from src.capital.fixed_percent import FixedPercentCapitalManager
from src.capital.martingale import MartingaleCapitalManager
from src.models.config import CapitalConfig
from src.models.exchange import MarketRules

__all__ = ["create_capital_manager"]

_MARTINGALE_MODES = frozenset({"martingale", "martingale_inverse"})


def create_capital_manager(config: CapitalConfig, market_rules: MarketRules) -> BaseCapitalManager:
    """Instancie le capital manager approprié selon le mode configuré (FR44, FR45, FR46).

    Args:
        config: Configuration du capital (mode, risk_percent, factor, max_steps).
        market_rules: Règles de marché de l'exchange (step_size, tick_size, etc.).

    Returns:
        Une instance de BaseCapitalManager correspondant au mode configuré.

    Raises:
        ValueError: Si le mode n'est pas reconnu.
    """
    if config.mode in _MARTINGALE_MODES:
        return MartingaleCapitalManager(config, market_rules)
    if config.mode == "fixed_percent":
        return FixedPercentCapitalManager(config.risk_percent, market_rules)
    raise ValueError(
        f"Mode capital non supporté: {config.mode!r}. "
        f"Modes valides : 'fixed_percent', 'martingale', 'martingale_inverse'"
    )
