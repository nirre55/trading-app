"""Tests pour l'orchestrateur principal TradingApp."""

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.app import TradingApp
from src.core.event_bus import EventBus
from src.core.exceptions import ConfigError, InsufficientBalanceError
from src.models.config import CapitalConfig, StrategyConfig
from src.models.events import AppEvent, EventType, StrategyEvent, TradeEvent
from src.models.exchange import Balance
from src.models.state import StrategyStateEnum


@pytest.fixture()
def app_config_file(tmp_path: Path) -> Path:
    """Crée un fichier de configuration temporaire valide."""
    logs_dir = (tmp_path / "logs").as_posix()
    trades_dir = (tmp_path / "trades").as_posix()
    state_file = (tmp_path / "state.json").as_posix()
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"""
exchange:
  name: "binance"
  api_key: "test_key_123"
  api_secret: "test_secret_456"
  testnet: true
paths:
  logs: "{logs_dir}"
  trades: "{trades_dir}"
  state: "{state_file}"
defaults:
  log_level: "INFO"
  risk_percent: 1.0
""",
        encoding="utf-8",
    )
    return config_file


@pytest.fixture()
def strategy_file(tmp_path: Path) -> tuple[Path, str]:
    """Crée un fichier de stratégie temporaire valide."""
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()
    strategy_path = strategies_dir / "ma-strat.yaml"
    strategy_path.write_text(
        """
name: "ma-strat"
pair: "BTC/USDT"
exchange: "binance"
timeframe: "1h"
leverage: 5
conditions:
  - type: "ema_cross"
    params:
      fast: 9
      slow: 21
timeout_candles: 10
capital:
  mode: "fixed_percent"
  risk_percent: 1.0
  risk_reward_ratio: 2.0
""",
        encoding="utf-8",
    )
    return strategies_dir, "ma-strat"


class TestTradingApp:
    """Tests de l'orchestrateur TradingApp."""

    @pytest.mark.asyncio
    async def test_trading_app_start(self, app_config_file: Path):
        app = TradingApp()
        await app.start(config_path=app_config_file)
        assert app.config is not None
        assert app.event_bus is not None

    @pytest.mark.asyncio
    async def test_trading_app_start_creates_log_dir(self, app_config_file: Path, tmp_path: Path):
        app = TradingApp()
        await app.start(config_path=app_config_file)
        logs_dir = tmp_path / "logs"
        assert logs_dir.exists()

    @pytest.mark.asyncio
    async def test_trading_app_start_emits_app_started(self, app_config_file: Path):
        app = TradingApp()
        with patch.object(EventBus, "emit", new_callable=AsyncMock) as mock_emit:
            await app.start(config_path=app_config_file)
            mock_emit.assert_called_once()
            event_type, event = mock_emit.call_args[0]
            assert event_type == EventType.APP_STARTED
            assert isinstance(event, AppEvent)

    @pytest.mark.asyncio
    async def test_trading_app_start_with_strategy(
        self, app_config_file: Path, strategy_file: tuple[Path, str]
    ):
        strategies_dir, strategy_name = strategy_file
        app = TradingApp()
        await app.start(
            config_path=app_config_file,
            strategy_name=strategy_name,
            strategies_dir=strategies_dir,
        )
        assert app.strategy_config is not None
        assert app.strategy_config.name == "ma-strat"

    @pytest.mark.asyncio
    async def test_trading_app_start_invalid_config(self, tmp_path: Path):
        app = TradingApp()
        with pytest.raises(ConfigError, match="introuvable"):
            await app.start(config_path=tmp_path / "nonexistent.yaml")

    @pytest.mark.asyncio
    async def test_trading_app_start_avec_telegram_cree_notification_service(self, tmp_path: Path):
        """Task 3.2 : start() avec Telegram activé → NotificationService instancié."""
        logs_dir = (tmp_path / "logs").as_posix()
        trades_dir = (tmp_path / "trades").as_posix()
        state_file = (tmp_path / "state.json").as_posix()
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            f"""
exchange:
  name: "binance"
  api_key: "test_key_123"
  api_secret: "test_secret_456"
  testnet: true
paths:
  logs: "{logs_dir}"
  trades: "{trades_dir}"
  state: "{state_file}"
defaults:
  log_level: "INFO"
telegram:
  enabled: true
  token: "bot123:AAAA"
  chat_id: "999"
""",
            encoding="utf-8",
        )
        app = TradingApp()
        await app.start(config_path=config_file)
        assert app.notification_service is not None

    @pytest.mark.asyncio
    async def test_trading_app_start_avec_telegram_enregistre_token(self, tmp_path: Path):
        """AC3 (intégration) : start() avec Telegram activé → token filtré des logs."""
        from src.core.logging import _sanitize_message

        token = "bot999:UNIQUE_SECRET_TOKEN_8_1"
        logs_dir = (tmp_path / "logs").as_posix()
        trades_dir = (tmp_path / "trades").as_posix()
        state_file = (tmp_path / "state.json").as_posix()
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            f"""
exchange:
  name: "binance"
  api_key: "test_key_123"
  api_secret: "test_secret_456"
  testnet: true
paths:
  logs: "{logs_dir}"
  trades: "{trades_dir}"
  state: "{state_file}"
defaults:
  log_level: "INFO"
telegram:
  enabled: true
  token: "{token}"
  chat_id: "999"
""",
            encoding="utf-8",
        )
        app = TradingApp()
        await app.start(config_path=config_file)
        sanitized = _sanitize_message(f"token actif : {token}")
        assert token not in sanitized
        assert "***" in sanitized


def _make_balance(free: Decimal = Decimal("100")) -> Balance:
    """Helper : crée une Balance valide avec free = total."""
    return Balance(total=free, free=free, used=Decimal("0"), currency="USDT")


class TestRunHealthCheck:
    """Tests unitaires de run_health_check() — vérifie connexion, API key, balance."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        app = TradingApp()
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.fetch_balance = AsyncMock(return_value=_make_balance(Decimal("100")))

        await app.run_health_check(mock_conn, min_balance=Decimal("10"))

        mock_conn.connect.assert_called_once()
        mock_conn.fetch_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_insufficient_balance_raises(self):
        app = TradingApp()
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.fetch_balance = AsyncMock(return_value=_make_balance(Decimal("5")))

        with pytest.raises(InsufficientBalanceError):
            await app.run_health_check(mock_conn, min_balance=Decimal("10"))

    @pytest.mark.asyncio
    async def test_health_check_connect_failure_propagates(self):
        from src.core.exceptions import ExchangeError

        app = TradingApp()
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock(side_effect=ExchangeError("timeout"))

        with pytest.raises(ExchangeError):
            await app.run_health_check(mock_conn, min_balance=Decimal("10"))

    @pytest.mark.asyncio
    async def test_health_check_exact_min_balance_passes(self):
        app = TradingApp()
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.fetch_balance = AsyncMock(return_value=_make_balance(Decimal("10")))

        await app.run_health_check(mock_conn, min_balance=Decimal("10"))

    @pytest.mark.asyncio
    async def test_health_check_appelle_send_startup_message(self):
        """AC5 : run_health_check() appelle send_startup_message() quand notification_service fourni."""
        app = TradingApp()
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.fetch_balance = AsyncMock(return_value=_make_balance(Decimal("100")))
        mock_notif = MagicMock()
        mock_notif.send_startup_message = AsyncMock()

        await app.run_health_check(mock_conn, min_balance=Decimal("10"), notification_service=mock_notif)

        mock_notif.send_startup_message.assert_called_once()


class TestRunLiveStateUpdates:
    """Tests de run_live() — vérifie la mise à jour de state.json sur événements (Task 5.2)."""

    def _setup_app(self, tmp_path: Path) -> tuple[TradingApp, EventBus, Path, Path]:
        """Configure un TradingApp avec état interne mocké."""
        state_file = tmp_path / "state.json"
        stop_flag = tmp_path / "stop.flag"

        app = TradingApp()
        mock_config = MagicMock()
        mock_config.paths.state = str(state_file)
        mock_config.paths.logs = str(tmp_path / "logs")
        mock_config.paths.backup = str(tmp_path / "backups")
        mock_config.defaults.backup_interval_hours = 86400  # 86 400 h ≫ durée des tests → backup_task ne s'exécute jamais
        mock_config.exchange = MagicMock()
        app.config = mock_config

        mock_strategy = MagicMock()
        mock_strategy.pair = "BTC/USDT"
        mock_strategy.timeframe = "1h"
        mock_strategy.name = "ma-strat"
        app.strategy_config = mock_strategy

        event_bus = EventBus()
        app.event_bus = event_bus
        return app, event_bus, state_file, stop_flag

    def _mock_connector(self) -> MagicMock:
        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()
        mock_conn.fetch_balance = AsyncMock(return_value=_make_balance(Decimal("100")))
        mock_conn.watch_candles = AsyncMock(return_value=None)
        mock_conn.disconnect = AsyncMock()
        return mock_conn

    @pytest.mark.asyncio
    async def test_state_json_written_at_startup(self, tmp_path: Path):
        app, _bus, state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            assert state_file.exists()
            data = json.loads(state_file.read_text())
            assert "uptime_start" in data

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)

    @pytest.mark.asyncio
    async def test_strategy_signal_updates_state_json(self, tmp_path: Path):
        app, event_bus, state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            await event_bus.emit(
                EventType.STRATEGY_SIGNAL_LONG,
                StrategyEvent(
                    event_type=EventType.STRATEGY_SIGNAL_LONG,
                    strategy_name="ma-strat",
                    pair="BTC/USDT",
                ),
            )
            await asyncio.sleep(0.05)

            data = json.loads(state_file.read_text())
            assert "ma-strat" in data["strategy_states"]
            assert data["strategy_states"]["ma-strat"]["state"] == StrategyStateEnum.SIGNAL_READY

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)

    @pytest.mark.asyncio
    async def test_trade_opened_updates_active_trades(self, tmp_path: Path):
        app, event_bus, state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            await event_bus.emit(
                EventType.TRADE_OPENED,
                TradeEvent(
                    event_type=EventType.TRADE_OPENED,
                    trade_id="trade-001",
                    pair="BTC/USDT",
                ),
            )
            await asyncio.sleep(0.05)

            data = json.loads(state_file.read_text())
            assert "trade-001" in data["active_trades"]

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)

    @pytest.mark.asyncio
    async def test_trade_closed_removes_from_active_trades(self, tmp_path: Path):
        app, event_bus, state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            await event_bus.emit(
                EventType.TRADE_OPENED,
                TradeEvent(event_type=EventType.TRADE_OPENED, trade_id="trade-001", pair="BTC/USDT"),
            )
            await asyncio.sleep(0.05)
            await event_bus.emit(
                EventType.TRADE_CLOSED,
                TradeEvent(event_type=EventType.TRADE_CLOSED, trade_id="trade-001", pair="BTC/USDT"),
            )
            await asyncio.sleep(0.05)

            data = json.loads(state_file.read_text())
            assert "trade-001" not in data["active_trades"]

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)


class TestPrintDryRunSummary:
    """Tests pour TradingApp._print_dry_run_summary (AC6, Story 9.2 — M2 fix)."""

    def _make_summary(
        self,
        initial: str | None = "1000",
        final: str | None = "1050",
        pnl: str = "50",
        count: int = 5,
    ) -> dict:
        from decimal import Decimal
        return {
            "initial_capital": Decimal(initial) if initial is not None else None,
            "final_capital": Decimal(final) if final is not None else None,
            "pnl_total": Decimal(pnl),
            "trades_count": count,
        }

    def test_affiche_header(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary())
        out = capsys.readouterr().out
        assert "[DRY-RUN] === Résumé de la session ===" in out

    def test_affiche_capital_initial(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(initial="1000"))
        out = capsys.readouterr().out
        assert "1000" in out
        assert "Capital initial" in out

    def test_affiche_capital_final(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(final="1050"))
        out = capsys.readouterr().out
        assert "1050" in out
        assert "Capital final" in out

    def test_affiche_pnl_positif_avec_signe_plus(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(pnl="50"))
        out = capsys.readouterr().out
        assert "+50.00" in out

    def test_affiche_pnl_negatif_sans_signe_plus(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(pnl="-30"))
        out = capsys.readouterr().out
        assert "-30.00" in out
        assert "+-30.00" not in out

    def test_affiche_trades_count(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(count=7))
        out = capsys.readouterr().out
        assert "7" in out
        assert "Trades simulés" in out

    def test_capital_none_affiche_na(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(initial=None, final=None))
        out = capsys.readouterr().out
        assert "N/A" in out

    def test_pnl_zero_affiche_signe_plus(self, capsys):
        TradingApp._print_dry_run_summary(self._make_summary(pnl="0"))
        out = capsys.readouterr().out
        assert "+0.00" in out


def _make_strategy_config(name: str = "rsi_ha") -> StrategyConfig:
    """Helper : StrategyConfig minimale pour les tests run_backtest()."""
    return StrategyConfig(
        name=name,
        pair="BTC/USDT",
        exchange="binance",
        timeframe="1h",
        leverage=1,
        conditions=[],
        timeout_candles=9999,
        capital=CapitalConfig(mode="fixed_percent", risk_percent=1.0, risk_reward_ratio=2.0),
    )


def _make_app_config_mock(tmp_path: Path) -> MagicMock:
    """Helper : AppConfig mocké pointant vers tmp_path."""
    mock_config = MagicMock()
    mock_config.paths.trades = str(tmp_path / "trades" / "trades.json")
    mock_config.paths.logs = str(tmp_path / "logs")
    mock_config.paths.state = str(tmp_path / "state.json")
    mock_config.defaults.backup_interval_hours = 86400
    return mock_config


class TestRunBacktest:
    """Tests pour run_backtest() — correctifs Story 10.4 (Bug #1/#2/#3).

    Vérifie que :
    - La stratégie est instanciée et câblée sur le bus (Bug #1)
    - strategy.stop() est toujours appelé, même en cas d'exception (fix M1)
    - TRADE_OPENED déclenche state_machine.on_trade_opened() (Bug #3)
    - Le guard empêche on_trade_closed() hors état IN_TRADE (fix M2)
    """

    def _setup_app(self, tmp_path: Path) -> tuple[TradingApp, MagicMock, MagicMock]:
        """Configure un TradingApp avec start() mocké."""
        app = TradingApp()
        mock_config = _make_app_config_mock(tmp_path)
        mock_strategy_config = _make_strategy_config()

        app.config = mock_config
        app.strategy_config = mock_strategy_config
        app.event_bus = EventBus()
        return app, mock_config, MagicMock()

    @pytest.mark.asyncio
    async def test_run_backtest_instancie_la_strategie_via_registry(self, tmp_path: Path):
        """Bug #1 : run_backtest() doit récupérer la classe via StrategyRegistry.get() et l'instancier."""
        app, _, _ = self._setup_app(tmp_path)
        mock_strategy = MagicMock()
        mock_strategy.stop = MagicMock()
        mock_state_machine = MagicMock()
        mock_state_machine.state = StrategyStateEnum.IDLE
        mock_state_machine.on_trade_opened = AsyncMock()
        mock_state_machine.on_trade_closed = AsyncMock()

        mock_strategy_cls = MagicMock(return_value=mock_strategy)
        mock_replay = MagicMock()
        mock_replay.run = AsyncMock()
        mock_simulator = MagicMock()
        mock_simulator.closed_trades = []
        mock_calculator = MagicMock()
        from src.backtest.metrics import BacktestMetrics, BacktestResult
        mock_calculator.compute.return_value = BacktestResult(
            metrics=BacktestMetrics(
                total_trades=0, win_rate=0.0, avg_rr=0.0, max_drawdown=0.0,
                max_consecutive_wins=0, max_consecutive_losses=0, profit_factor=0.0,
            ),
            trades=[],
        )

        with (
            patch("src.core.app.DataDownloader"),
            patch("src.core.app.ReplayEngine", return_value=mock_replay),
            patch("src.core.app.TradeSimulator", return_value=mock_simulator),
            patch("src.core.app.create_capital_manager"),
            patch("src.core.app.StateMachine", return_value=mock_state_machine),
            patch("src.core.app.StrategyRegistry") as mock_registry,
            patch("src.core.app.MetricsCalculator", return_value=mock_calculator),
            patch.object(app, "start", new_callable=AsyncMock),
        ):
            mock_registry.get.return_value = mock_strategy_cls
            await app.run_backtest(
                strategy_name="rsi_ha",
                start_dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_dt=datetime(2024, 12, 31, tzinfo=timezone.utc),
            )

        mock_registry.get.assert_called_once_with("rsi_ha")
        mock_strategy_cls.assert_called_once()
        mock_strategy.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_backtest_strategy_stop_appelee_si_exception_replay(self, tmp_path: Path):
        """Fix M1 : strategy.stop() doit être appelé même si replay_engine.run() lève une exception."""
        app, _, _ = self._setup_app(tmp_path)
        mock_strategy = MagicMock()
        mock_strategy.stop = MagicMock()
        mock_state_machine = MagicMock()
        mock_state_machine.state = StrategyStateEnum.IDLE
        mock_state_machine.on_trade_opened = AsyncMock()
        mock_state_machine.on_trade_closed = AsyncMock()

        mock_strategy_cls = MagicMock(return_value=mock_strategy)
        mock_replay = MagicMock()
        mock_replay.run = AsyncMock(side_effect=RuntimeError("Erreur réseau simulée"))
        mock_simulator = MagicMock()
        mock_simulator.closed_trades = []

        with (
            patch("src.core.app.DataDownloader"),
            patch("src.core.app.ReplayEngine", return_value=mock_replay),
            patch("src.core.app.TradeSimulator", return_value=mock_simulator),
            patch("src.core.app.create_capital_manager"),
            patch("src.core.app.StateMachine", return_value=mock_state_machine),
            patch("src.core.app.StrategyRegistry") as mock_registry,
            patch("src.core.app.MetricsCalculator"),
            patch.object(app, "start", new_callable=AsyncMock),
        ):
            mock_registry.get.return_value = mock_strategy_cls
            with pytest.raises(RuntimeError, match="Erreur réseau simulée"):
                await app.run_backtest(
                    strategy_name="rsi_ha",
                    start_dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end_dt=datetime(2024, 12, 31, tzinfo=timezone.utc),
                )

        mock_strategy.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_backtest_trade_opened_appelle_state_machine(self, tmp_path: Path):
        """Bug #3 : TRADE_OPENED doit déclencher state_machine.on_trade_opened()."""
        app, _, _ = self._setup_app(tmp_path)
        mock_strategy = MagicMock()
        mock_strategy.stop = MagicMock()
        mock_state_machine = MagicMock()
        mock_state_machine.state = StrategyStateEnum.SIGNAL_READY
        mock_state_machine.on_trade_opened = AsyncMock()
        mock_state_machine.on_trade_closed = AsyncMock()

        mock_strategy_cls = MagicMock(return_value=mock_strategy)
        mock_simulator = MagicMock()
        mock_simulator.closed_trades = []
        mock_calculator = MagicMock()
        from src.backtest.metrics import BacktestMetrics, BacktestResult
        mock_calculator.compute.return_value = BacktestResult(
            metrics=BacktestMetrics(
                total_trades=0, win_rate=0.0, avg_rr=0.0, max_drawdown=0.0,
                max_consecutive_wins=0, max_consecutive_losses=0, profit_factor=0.0,
            ),
            trades=[],
        )

        # replay.run() émet un TRADE_OPENED pendant son exécution
        async def replay_with_trade_event(*args, **kwargs):
            await app.event_bus.emit(
                EventType.TRADE_OPENED,
                TradeEvent(event_type=EventType.TRADE_OPENED, trade_id="bt-001", pair="BTC/USDT"),
            )

        mock_replay = MagicMock()
        mock_replay.run = AsyncMock(side_effect=replay_with_trade_event)

        with (
            patch("src.core.app.DataDownloader"),
            patch("src.core.app.ReplayEngine", return_value=mock_replay),
            patch("src.core.app.TradeSimulator", return_value=mock_simulator),
            patch("src.core.app.create_capital_manager"),
            patch("src.core.app.StateMachine", return_value=mock_state_machine),
            patch("src.core.app.StrategyRegistry") as mock_registry,
            patch("src.core.app.MetricsCalculator", return_value=mock_calculator),
            patch.object(app, "start", new_callable=AsyncMock),
        ):
            mock_registry.get.return_value = mock_strategy_cls
            await app.run_backtest(
                strategy_name="rsi_ha",
                start_dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_dt=datetime(2024, 12, 31, tzinfo=timezone.utc),
            )

        mock_state_machine.on_trade_opened.assert_called_once_with("bt-001")

    @pytest.mark.asyncio
    async def test_run_backtest_on_trade_closed_guard_etat_non_in_trade(self, tmp_path: Path):
        """Fix M2 : TRADE_CLOSED ignoré si state_machine n'est pas en état IN_TRADE."""
        app, _, _ = self._setup_app(tmp_path)
        mock_strategy = MagicMock()
        mock_strategy.stop = MagicMock()
        mock_state_machine = MagicMock()
        # État != IN_TRADE → le guard doit bloquer l'appel
        mock_state_machine.state = StrategyStateEnum.IDLE
        mock_state_machine.on_trade_opened = AsyncMock()
        mock_state_machine.on_trade_closed = AsyncMock()

        mock_strategy_cls = MagicMock(return_value=mock_strategy)
        mock_simulator = MagicMock()
        mock_simulator.closed_trades = []
        mock_calculator = MagicMock()
        from src.backtest.metrics import BacktestMetrics, BacktestResult
        mock_calculator.compute.return_value = BacktestResult(
            metrics=BacktestMetrics(
                total_trades=0, win_rate=0.0, avg_rr=0.0, max_drawdown=0.0,
                max_consecutive_wins=0, max_consecutive_losses=0, profit_factor=0.0,
            ),
            trades=[],
        )

        async def replay_with_spurious_trade_closed(*args, **kwargs):
            await app.event_bus.emit(
                EventType.TRADE_CLOSED,
                TradeEvent(event_type=EventType.TRADE_CLOSED, trade_id="bt-001", pair="BTC/USDT"),
            )

        mock_replay = MagicMock()
        mock_replay.run = AsyncMock(side_effect=replay_with_spurious_trade_closed)

        with (
            patch("src.core.app.DataDownloader"),
            patch("src.core.app.ReplayEngine", return_value=mock_replay),
            patch("src.core.app.TradeSimulator", return_value=mock_simulator),
            patch("src.core.app.create_capital_manager"),
            patch("src.core.app.StateMachine", return_value=mock_state_machine),
            patch("src.core.app.StrategyRegistry") as mock_registry,
            patch("src.core.app.MetricsCalculator", return_value=mock_calculator),
            patch.object(app, "start", new_callable=AsyncMock),
        ):
            mock_registry.get.return_value = mock_strategy_cls
            await app.run_backtest(
                strategy_name="rsi_ha",
                start_dt=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_dt=datetime(2024, 12, 31, tzinfo=timezone.utc),
            )

        mock_state_machine.on_trade_closed.assert_not_called()
