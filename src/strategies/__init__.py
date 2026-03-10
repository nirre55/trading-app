from src.strategies.example_strategy import ExampleStrategy
from src.strategies.registry import StrategyRegistry
from src.strategies.rsi_ha_strategy import RsiHaStrategy  # Déclenche l'auto-enregistrement

__all__ = ["ExampleStrategy", "StrategyRegistry", "RsiHaStrategy"]
