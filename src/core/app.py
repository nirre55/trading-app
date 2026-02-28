"""Orchestrateur principal de l'application trading-app."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from loguru import logger

from src.backtest.data_downloader import DataDownloader
from src.backtest.metrics import BacktestResult, MetricsCalculator
from src.backtest.replay_engine import ReplayEngine
from src.backtest.trade_simulator import TradeSimulator
from src.capital.factory import create_capital_manager
from src.core.backup import LogBackupService
from src.core.config import load_app_config, load_strategy_by_name
from src.core.event_bus import EventBus
from src.core.exceptions import InsufficientBalanceError
from src.core.lock import LockFile
from src.core.state_manager import StateManager
from src.core.logging import register_sensitive_values, setup_logging
from src.exchange.ccxt_connector import CcxtConnector
from src.models.config import AppConfig, StrategyConfig
from src.models.events import AppEvent, BaseEvent, ErrorEvent, EventType, StrategyEvent, TradeEvent
from src.models.exchange import MarketRules, OrderSide, OrderType
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

    async def run_crash_recovery(
        self,
        connector: CcxtConnector,
        state_manager: StateManager,
        pair: str,
    ) -> AppState | None:
        """Recovery après crash : vérifie et protège les positions ouvertes (FR42, NFR8).

        Returns:
            AppState restauré si recovery effectuée, None si démarrage propre.
        """
        state = state_manager.load()

        if state is None or not state.active_trades:
            logger.debug("ℹ️ Démarrage propre — pas de recovery nécessaire")
            return None

        logger.warning(
            "⚠️ {} trade(s) actif(s) détecté(s) sur {} — démarrage en mode recovery...",
            len(state.active_trades),
            pair,
        )

        try:
            async with asyncio.timeout(55):  # Marge sous 60s (NFR8)
                positions = await connector.fetch_positions()
                open_orders = await connector.fetch_open_orders()

                # Identifier les ordres de protection (SL + TP)
                protection_types = {
                    "stop_market", "stop", "stop_loss", "take_profit_market", "take_profit"
                }
                protection_orders = [
                    o for o in open_orders
                    if o.get("type", "").lower() in protection_types
                    or o.get("stopPrice") is not None
                    or o.get("triggerPrice") is not None
                ]
                has_protection = len(protection_orders) > 0

                # Chercher la position ouverte UNE SEULE FOIS — partagée par tous les trade_ids
                # (système single-pair : tous les trade_ids actifs correspondent à la même position)
                open_position = next(
                    (p for p in positions if float(p.get("contracts", 0)) > 0),
                    None,
                )

                # Traitement de chaque trade actif
                for trade_id in list(state.active_trades):
                    if open_position is None:
                        # Position fermée pendant le crash (SL/TP hit ou fermeture externe)
                        logger.info(
                            "ℹ️ Trade {} : position absente sur l'exchange — trade terminé hors système",
                            trade_id,
                        )
                        state.active_trades.remove(trade_id)
                        continue

                    if has_protection:
                        logger.info(
                            "✅ Trade {} : position protégée ({} ordres TP/SL) — monitoring reprend",
                            trade_id,
                            len(protection_orders),
                        )
                    else:
                        # CRITIQUE : position sans protection → fermeture immédiate (FR42)
                        logger.critical(
                            "🚨 Trade {} : position SANS TP/SL sur l'exchange — fermeture immédiate!",
                            trade_id,
                        )
                        side = open_position.get("side", "long").lower()
                        close_qty = Decimal(str(open_position.get("contracts", 0)))

                        close_side = OrderSide.SELL if side == "long" else OrderSide.BUY
                        await connector.place_order(close_side, OrderType.MARKET, close_qty)
                        logger.info("Position {} fermée via ordre MARKET", trade_id)
                        state.active_trades.remove(trade_id)
                        open_position = None  # Position fermée — absente pour les trades suivants

                        if self.event_bus is not None:
                            await self.event_bus.emit(
                                EventType.ERROR_CRITICAL,
                                ErrorEvent(
                                    event_type=EventType.ERROR_CRITICAL,
                                    error_type="RecoveryCritical",
                                    message=f"Position {trade_id} fermée en recovery (TP/SL absents)",
                                ),
                            )

                # Persister l'état corrigé après recovery
                state_manager.save(state)
                logger.info("✅ Recovery terminée — état sauvegardé")
                return state

        except asyncio.TimeoutError:
            logger.error(
                "❌ Recovery timeout dépassé (> 55s) — certaines positions non vérifiées (NFR8)"
            )
            return state  # Retourner l'état partiel

    async def _verify_tpsl_on_shutdown(
        self,
        connector: CcxtConnector,
        app_state: AppState,
    ) -> None:
        """Vérifie les ordres TP/SL avant fermeture et logge le résultat (AC2, FR41).

        Non-bloquant : les erreurs exchange sont loggées, jamais propagées.
        """
        if not app_state.active_trades:
            logger.info("ℹ️ Arrêt — aucun trade actif, vérification TP/SL non requise")
            return
        try:
            positions = await connector.fetch_positions()
            open_orders = await connector.fetch_open_orders()
            protection_types = {
                "stop_market", "stop", "stop_loss", "take_profit_market", "take_profit"
            }
            protection_orders = [
                o for o in open_orders
                if o.get("type", "").lower() in protection_types
                or o.get("stopPrice") is not None
                or o.get("triggerPrice") is not None
            ]
            if positions:
                if protection_orders:
                    logger.info(
                        "✅ Shutdown : {} position(s) ouverte(s), {} ordre(s) TP/SL en place",
                        len(positions),
                        len(protection_orders),
                    )
                else:
                    logger.warning(
                        "⚠️ Shutdown : {} position(s) ouverte(s) SANS ordre TP/SL détecté — vérifiez manuellement !",
                        len(positions),
                    )
            else:
                logger.info("ℹ️ Shutdown : aucune position ouverte sur l'exchange")
        except Exception as exc:
            logger.error("❌ Impossible de vérifier les TP/SL avant arrêt : {}", exc)

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
        app_state: AppState | None = None  # Accessible dans finally pour _verify_tpsl_on_shutdown
        try:
            connector = CcxtConnector(
                self.config.exchange,
                self.event_bus,
                self.strategy_config.pair,
                self.strategy_config.timeframe,
            )
            await self.run_health_check(connector, min_balance)

            # Création du StateManager avant crash recovery
            state_manager = StateManager(state_file)

            # Crash recovery : vérifie positions ouvertes si state.json existe (FR42)
            recovered_state = await self.run_crash_recovery(
                connector, state_manager, self.strategy_config.pair
            )
            app_state = recovered_state if recovered_state is not None else AppState()
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

            # Gestion des signaux SIGTERM/SIGINT (FR41)
            shutdown_event = asyncio.Event()
            if sys.platform != "win32":
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
                loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
            else:
                loop = asyncio.get_running_loop()  # Capturer dans le contexte async (non déprécié)
                def _win_handler(sig: int, frame: object) -> None:
                    loop.call_soon_threadsafe(shutdown_event.set)
                signal.signal(signal.SIGINT, _win_handler)

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
                while not stop_flag.exists() and not shutdown_event.is_set():
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
            # AC2 : vérification TP/SL avant fermeture — logge l'état des positions (FR41)
            if connector is not None and app_state is not None:
                await self._verify_tpsl_on_shutdown(connector, app_state)
            if connector is not None:
                await connector.disconnect()
            lock.release()
            stop_flag.unlink(missing_ok=True)
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
        initial_capital: Decimal = Decimal("10000"),
    ) -> BacktestResult:
        """Orchestre un backtest complet : téléchargement → replay → métriques (FR21-FR26).

        Args:
            strategy_name: Nom de la stratégie à backtester.
            start_dt: Date/heure de début (TZ-aware UTC).
            end_dt: Date/heure de fin (TZ-aware UTC).
            output_path: Chemin pour exporter les résultats en JSON (optionnel).
            config_path: Chemin vers le fichier de configuration (optionnel).
            initial_capital: Capital de départ du backtest en USDT (défaut : 10000).
        """
        await self.start(config_path=config_path, strategy_name=strategy_name)
        if self.config is None or self.strategy_config is None or self.event_bus is None:
            raise RuntimeError("run_backtest() : état interne invalide après start()")

        # Dériver data_dir depuis paths.trades (ex: "data/trades" → "data/")
        data_dir = Path(self.config.paths.trades).parent
        downloader = DataDownloader(data_dir / "historical")
        replay_engine = ReplayEngine(downloader, self.event_bus)

        capital_manager = create_capital_manager(
            self.strategy_config.capital,
            _DEFAULT_BACKTEST_MARKET_RULES,
        )
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
