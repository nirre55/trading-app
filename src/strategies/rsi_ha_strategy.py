"""Stratégie RSI multi-période + Heikin-Ashi : détection de retournements."""

from decimal import Decimal
from typing import Any

from loguru import logger

from src.core.exceptions import ConfigError
from src.indicators.heikin_ashi import HeikinAshiIndicator
from src.indicators.rsi import RSIIndicator
from src.models.config import StrategyConfig
from src.models.events import CandleEvent
from src.strategies.base import BaseStrategy
from src.strategies.registry import StrategyRegistry

__all__ = ["RsiHaStrategy"]


@StrategyRegistry.strategy("rsi_ha")
class RsiHaStrategy(BaseStrategy):
    """Stratégie 2 phases : 3 RSI en zone simultanément + confirmation HA.

    Phase 1 : Les 3 RSI (périodes 3, 5, 7) doivent être simultanément dans
              leur zone oversold (LONG) ou overbought (SHORT).
    Phase 2 : Attente indéfinie de la première bougie HA confirmatrice.

    SL = min(low) des sl_lookback_candles dernières bougies (LONG)
       = max(high) des sl_lookback_candles dernières bougies (SHORT)
    TP calculé par CapitalManager via risk_reward_ratio (config capital).
    """

    def __init__(
        self,
        config: StrategyConfig,
        state_machine: Any,
        event_bus: Any,
    ) -> None:
        super().__init__(config, state_machine, event_bus)

        params: dict[str, Any] = config.conditions[0].params if config.conditions else {}

        self._rsi_periods: list[int] = params.get("rsi_periods", [3, 5, 7])
        self._rsi_oversold: list[float] = params.get("rsi_oversold_levels", [10, 20, 30])
        self._rsi_overbought: list[float] = params.get("rsi_overbought_levels", [90, 80, 70])
        self._sl_lookback: int = params.get("sl_lookback_candles", 5)

        # Validation
        if not (len(self._rsi_periods) == len(self._rsi_oversold) == len(self._rsi_overbought)):
            raise ConfigError(
                "rsi_periods, rsi_oversold_levels et rsi_overbought_levels "
                "doivent avoir la même longueur",
                context={"periods": self._rsi_periods},
            )
        for i, (os, ob) in enumerate(zip(self._rsi_oversold, self._rsi_overbought)):
            if os >= ob:
                raise ConfigError(
                    f"rsi_oversold_levels[{i}]={os} doit être < rsi_overbought_levels[{i}]={ob}",
                    context={"index": i, "oversold": os, "overbought": ob},
                )

        # Indicateurs
        self._rsi_indicators: list[RSIIndicator] = [
            RSIIndicator(period=p) for p in self._rsi_periods
        ]
        self._ha_indicator = HeikinAshiIndicator()

        # Borne de l'historique : max(10×période_max, sl_lookback) bougies suffisent
        # pour la convergence Wilder et le calcul SL — évite la dégradation O(n²)
        self._max_rsi_period: int = max(self._rsi_periods)
        self._history_max_size: int = max(self._max_rsi_period * 10, self._sl_lookback)

        # État interne
        self._signal_direction: str | None = None
        self._computed_sl_price: Decimal | None = None
        self._candle_history: list[CandleEvent] = []

        logger.debug(
            "RsiHaStrategy initialisée — périodes={}, oversold={}, overbought={}, sl_lookback={}",
            self._rsi_periods,
            self._rsi_oversold,
            self._rsi_overbought,
            self._sl_lookback,
        )

    async def evaluate_conditions(self, candle: CandleEvent) -> None:
        """Évalue les 2 phases séquentielles sans timeout."""
        self._candle_history.append(candle)
        if len(self._candle_history) > self._history_max_size:
            self._candle_history.pop(0)
        conditions_met = len(self._state_machine.conditions_met)

        if conditions_met == 0:
            # Réinitialiser l'état au début de chaque nouveau cycle (réutilisation de la stratégie)
            self._signal_direction = None
            self._computed_sl_price = None
            # Phase 1 : Les 3 RSI doivent être en zone simultanément
            direction = self._check_rsi_zone()
            if direction is not None:
                self._signal_direction = direction
                logger.info(
                    "RsiHaStrategy '{}' : Phase 1 validée — direction={}, bougie #{}",
                    self._config.name,
                    direction,
                    self._candle_count,
                )
                await self._state_machine.on_condition_met(0, self._candle_count)

        elif conditions_met == 1:
            # Phase 2 : Attente indéfinie de la confirmation HA
            if self._check_ha_confirmation():
                self._compute_sl_price()
                logger.info(
                    "RsiHaStrategy '{}' : Phase 2 confirmée HA — signal={}, sl={}",
                    self._config.name,
                    self._signal_direction,
                    self._computed_sl_price,
                )
                await self._state_machine.on_all_conditions_met(
                    self._signal_direction or "long",
                    signal_price=candle.close,
                    sl_price=self._computed_sl_price,
                )

    def _check_rsi_zone(self) -> str | None:
        """Vérifie si les 3 RSI sont simultanément en zone oversold ou overbought."""
        if len(self._candle_history) < self._max_rsi_period + 1:
            return None  # Données insuffisantes pour le RSI le plus long

        candles = self._candle_history
        rsi_last_values: list[Decimal | None] = []
        for indicator in self._rsi_indicators:
            values = indicator.compute(candles)
            rsi_last_values.append(values[-1] if values else None)

        # Vérifier oversold (LONG) : tous les RSI <= leurs seuils respectifs
        if all(
            v is not None and v <= Decimal(str(self._rsi_oversold[i]))
            for i, v in enumerate(rsi_last_values)
        ):
            logger.debug(
                "RsiHaStrategy : RSI tous oversold — valeurs={}", rsi_last_values
            )
            return "long"

        # Vérifier overbought (SHORT) : tous les RSI >= leurs seuils respectifs
        if all(
            v is not None and v >= Decimal(str(self._rsi_overbought[i]))
            for i, v in enumerate(rsi_last_values)
        ):
            logger.debug(
                "RsiHaStrategy : RSI tous overbought — valeurs={}", rsi_last_values
            )
            return "short"

        return None

    def _check_ha_confirmation(self) -> bool:
        """Vérifie si la bougie HA courante confirme la direction attendue."""
        if len(self._candle_history) < 2:
            return False
        ha_values = self._ha_indicator.compute(self._candle_history)
        last_ha = ha_values[-1] if ha_values else None
        if last_ha is None:
            return False
        if self._signal_direction == "long":
            return last_ha == Decimal(1)  # Bougie HA bullish
        if self._signal_direction == "short":
            return last_ha == Decimal(0)  # Bougie HA bearish
        return False

    def _compute_sl_price(self) -> None:
        """Calcule le SL depuis les N dernières bougies (incluant la courante)."""
        lookback = self._candle_history[-self._sl_lookback :]
        if self._signal_direction == "long":
            self._computed_sl_price = min(c.low for c in lookback)
        elif self._signal_direction == "short":
            self._computed_sl_price = max(c.high for c in lookback)

    def get_signal(self) -> str:
        """Retourne la direction du signal : 'long' ou 'short'."""
        return self._signal_direction or "long"

    def get_sl_price(self) -> Decimal | None:
        """Retourne le prix Stop-Loss calculé (disponible après confirmation HA)."""
        return self._computed_sl_price
