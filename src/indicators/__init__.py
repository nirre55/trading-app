from src.indicators.base import BaseIndicator
from src.indicators.registry import IndicatorRegistry
from src.indicators.rsi import RSIIndicator  # Déclenche l'auto-enregistrement

__all__ = ["BaseIndicator", "IndicatorRegistry", "RSIIndicator"]
