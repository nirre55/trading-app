from src.indicators.base import BaseIndicator
from src.indicators.heikin_ashi import HeikinAshiIndicator  # Déclenche l'auto-enregistrement
from src.indicators.registry import IndicatorRegistry
from src.indicators.rsi import RSIIndicator  # Déclenche l'auto-enregistrement

__all__ = ["BaseIndicator", "HeikinAshiIndicator", "IndicatorRegistry", "RSIIndicator"]
