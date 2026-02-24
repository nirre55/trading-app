"""Orchestrateur principal de l'application trading-app."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from loguru import logger

from src.backtest.data_downloader import DataDownloader
from src.backtest.metrics import BacktestResult, MetricsCalculator
from src.backtest.replay_engine import ReplayEngine
from src.backtest.trade_simulator import TradeSimulator
from src.capital.fixed_percent import FixedPercentCapitalManager
from src.core.backup import LogBackupService
from src.core.config import load_app_config, load_strategy_by_name
from src.core.event_bus import EventBus
from src.core.exceptions import InsufficientBalanceError
from src.core.lock import LockFile
from src.core.state_manager import StateManager
from src.core.logging import register_sensitive_values, setup_logging
from src.exchange.ccxt_connector import CcxtConnector
from src.models.config import AppConfig, StrategyConfig
from src.models.events import AppEvent, BaseEvent, EventType, StrategyEvent, TradeEvent
from src.models.exchange import MarketRules
from src.models.state import AppState, StrategyState, StrategyStateEnum

# Market rules par défaut pour le backtest (pas de fetching exchange en mode simulation)
_DEFAULT_BACKTEST_MARKET_RULES = MarketRules(
    step_size=Decimal("0.001"),
    tick_size=Decimal("0.01"),
    min_notional=Decimal("5"),
    max_leverage=125,
)

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
        # Enregistrer les valeurs brutes des clés API pour filtrage dynamique (FR34, NFR4)
        sensitive: list[str] = [
            self.config.exchange.api_key.get_secret_value(),
            self.config.exchange.api_secret.get_secret_value(),
        ]
        if self.config.exchange.password is not None:
            sensitive.append(self.config.exchange.password.get_secret_value())
        register_sensitive_values(*sensitive)

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

    async def run_health_check(
        self,
        connector: CcxtConnector,
        min_balance: Decimal = Decimal("10"),
    ) -> None:
        """Health check complet : connexion, API key, balance (FR39).

        Args:
            connector: Connecteur exchange à vérifier.
            min_balance: Balance minimale requise (USDT).
        """
        logger.info("🔍 Health check démarré...")
        await connector.connect()
        logger.info("✓ Connexion exchange établie")
        balance = await connector.fetch_balance()
        logger.info("✓ Clé API valide — balance={} {}", balance.free, balance.currency)
        if balance.free < min_balance:
            raise InsufficientBalanceError(
                f"Balance insuffisante : {balance.free} {balance.currency} < {min_balance} requis",
                context={"balance": str(balance.free), "min_required": str(min_balance)},
            )
        logger.info("✓ Balance suffisante ({} {})", balance.free, balance.currency)
        logger.info("✅ Health check réussi — système prêt")

    async def run_live(
        self,
        strategy_name: str,
        config_path: Path | None = None,
        min_balance: Decimal = Decimal("10"),
    ) -> None:
        """Boucle de trading live : config, health check, écoute des bougies.

        Args:
            strategy_name: Nom de la stratégie à exécuter.
            config_path: Chemin vers le fichier de configuration (optionnel).
            min_balance: Balance minimale requise en USDT.
        """
        await self.start(config_path=config_path, strategy_name=strategy_name)
        if self.config is None or self.strategy_config is None or self.event_bus is None:
            raise RuntimeError("run_live() : état interne invalide après start()")

        # Dériver data_dir depuis paths.state (ex: "data/state.json" → "data/")
        data_dir = Path(self.config.paths.state).parent
        stop_flag = data_dir / "stop.flag"
        # Nettoyage d'un stop.flag périmé
        stop_flag.unlink(missing_ok=True)

        state_file = Path(self.config.paths.state)

        # Acquisition du lock AVANT le connecteur — LockError propagée avant toute création (FR40)
        lock_path = data_dir / "trading.lock"
        lock = LockFile(lock_path)
        lock.acquire()

        # Initialisation connecteur — connecteur=None jusqu'à sa création pour garantir
        # que lock.release() s'exécute même si CcxtConnector() lève avant le try (FR40)
        connector: CcxtConnector | None = None
        try:
            connector = CcxtConnector(
                self.config.exchange,
                self.event_bus,
                self.strategy_config.pair,
                self.strategy_config.timeframe,
            )
            await self.run_health_check(connector, min_balance)

            # Écriture de l'état initial
            app_state = AppState()
            state_manager = StateManager(state_file)
            state_manager.save(app_state)

            # Abonnements bus — mise à jour de app_state sur événements strategy/trade (Task 5.2)
            async def _on_strategy_event(event: BaseEvent) -> None:
                if not isinstance(event, StrategyEvent):
                    return
                s = app_state.strategy_states.setdefault(
                    event.strategy_name, StrategyState(state=StrategyStateEnum.IDLE)
                )
                if event.event_type in (EventType.STRATEGY_SIGNAL_LONG, EventType.STRATEGY_SIGNAL_SHORT):
                    s.state = StrategyStateEnum.SIGNAL_READY
                    s.conditions_met.clear()
                elif event.event_type == EventType.STRATEGY_CONDITION_MET:
                    s.state = StrategyStateEnum.WATCHING
                    if event.condition_index is not None and event.condition_index not in s.conditions_met:
                        s.conditions_met.append(event.condition_index)
                elif event.event_type == EventType.STRATEGY_TIMEOUT:
                    s.state = StrategyStateEnum.IDLE
                    s.conditions_met.clear()
                state_manager.save(app_state)

            async def _on_trade_event(event: BaseEvent) -> None:
                if not isinstance(event, TradeEvent):
                    return
                if event.event_type == EventType.TRADE_OPENED:
                    if event.trade_id not in app_state.active_trades:
                        app_state.active_trades.append(event.trade_id)
                    for s in app_state.strategy_states.values():
                        if s.state == StrategyStateEnum.SIGNAL_READY:
                            s.state = StrategyStateEnum.IN_TRADE
                elif event.event_type == EventType.TRADE_CLOSED:
                    if event.trade_id in app_state.active_trades:
                        app_state.active_trades.remove(event.trade_id)
                    if not app_state.active_trades:
                        for s in app_state.strategy_states.values():
                            if s.state == StrategyStateEnum.IN_TRADE:
                                s.state = StrategyStateEnum.IDLE
                state_manager.save(app_state)

            for et in (
                EventType.STRATEGY_CONDITION_MET,
                EventType.STRATEGY_SIGNAL_LONG,
                EventType.STRATEGY_SIGNAL_SHORT,
                EventType.STRATEGY_TIMEOUT,
            ):
                self.event_bus.on(et, _on_strategy_event)
            for et in (EventType.TRADE_OPENED, EventType.TRADE_CLOSED):
                self.event_bus.on(et, _on_trade_event)

            # Démarrage de la boucle principale
            logger.info("🚀 Boucle de trading démarrée pour '{}'", self.strategy_config.name)
            candle_task = asyncio.create_task(connector.watch_candles())
            backup_service = LogBackupService()
            backup_task = asyncio.create_task(
                backup_service.run(
                    Path(self.config.paths.logs),
                    Path(self.config.paths.backup),
                    self.config.defaults.backup_interval_hours,
                )
            )
            try:
                while not stop_flag.exists():
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                pass
            finally:
                candle_task.cancel()
                backup_task.cancel()
                try:
                    await candle_task
                except asyncio.CancelledError:
                    pass
                try:
                    await backup_task
                except asyncio.CancelledError:
                    pass
        finally:
            if connector is not None:
                await connector.disconnect()
            lock.release()
            stop_flag.unlink(missing_ok=True)
            state_file.unlink(missing_ok=True)
            await self.event_bus.emit(
                EventType.APP_STOPPED,
                AppEvent(event_type=EventType.APP_STOPPED),
            )
            logger.info("⏹ Application arrêtée proprement")

    async def run_backtest(
        self,
        strategy_name: str,
        start_dt: datetime,
        end_dt: datetime,
        output_path: Path | None = None,
        config_path: Path | None = None,
    ) -> BacktestResult:
        """Orchestre un backtest complet : téléchargement → replay → métriques (FR21-FR26).

        Args:
            strategy_name: Nom de la stratégie à backtester.
            start_dt: Date/heure de début (TZ-aware UTC).
            end_dt: Date/heure de fin (TZ-aware UTC).
            output_path: Chemin pour exporter les résultats en JSON (optionnel).
            config_path: Chemin vers le fichier de configuration (optionnel).
        """
        await self.start(config_path=config_path, strategy_name=strategy_name)
        if self.config is None or self.strategy_config is None or self.event_bus is None:
            raise RuntimeError("run_backtest() : état interne invalide après start()")

        # Dériver data_dir depuis paths.trades (ex: "data/trades" → "data/")
        data_dir = Path(self.config.paths.trades).parent
        downloader = DataDownloader(data_dir / "historical")
        replay_engine = ReplayEngine(downloader, self.event_bus)

        capital_manager = FixedPercentCapitalManager(
            self.strategy_config.capital.risk_percent,
            _DEFAULT_BACKTEST_MARKET_RULES,
        )
        initial_capital = Decimal("10000")
        simulator = TradeSimulator(
            self.event_bus, self.strategy_config, capital_manager, initial_capital
        )

        await replay_engine.run(
            self.strategy_config.exchange,
            self.strategy_config.pair,
            self.strategy_config.timeframe,
            start_dt,
            end_dt,
        )

        calculator = MetricsCalculator()
        result = calculator.compute(simulator.closed_trades)

        if output_path is not None:
            calculator.export_json(result, output_path)

        return result
