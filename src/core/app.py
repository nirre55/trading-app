"""Orchestrateur principal de l'application trading-app."""

from pathlib import Path

from loguru import logger

from src.core.config import load_app_config, load_strategy_by_name
from src.core.event_bus import EventBus
from src.core.logging import setup_logging
from src.models.config import AppConfig, StrategyConfig
from src.models.events import AppEvent, EventType

__all__ = ["TradingApp"]


class TradingApp:
    """Orchestrateur lifecycle de l'application trading-app."""

    def __init__(self) -> None:
        self.config: AppConfig | None = None
        self.strategy_config: StrategyConfig | None = None
        self.event_bus: EventBus | None = None

    async def start(
        self,
        config_path: Path | None = None,
        strategy_name: str | None = None,
        strategies_dir: Path | None = None,
    ) -> None:
        """Démarre l'application : charge config, logging, bus, événement.

        Args:
            config_path: Chemin vers le fichier de configuration principal.
            strategy_name: Nom de la stratégie à charger (optionnel).
            strategies_dir: Répertoire des fichiers de stratégie (optionnel).
        """
        self.config = load_app_config(config_path)

        setup_logging(
            log_level=self.config.defaults.log_level,
            log_dir=self.config.paths.logs,
        )

        if strategy_name is not None:
            self.strategy_config = load_strategy_by_name(
                strategy_name, strategies_dir=strategies_dir
            )

        self.event_bus = EventBus()

        await self.event_bus.emit(
            EventType.APP_STARTED,
            AppEvent(event_type=EventType.APP_STARTED),
        )

        logger.info("Application trading-app démarrée")
