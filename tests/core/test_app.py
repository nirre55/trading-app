"""Tests pour l'orchestrateur principal TradingApp."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.app import TradingApp
from src.core.event_bus import EventBus
from src.core.exceptions import ConfigError, InsufficientBalanceError
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
  mode: "fixed"
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


class TestRunLiveStateUpdates:
    """Tests de run_live() — vérifie la mise à jour de state.json sur événements (Task 5.2)."""

    def _setup_app(self, tmp_path: Path) -> tuple[TradingApp, EventBus, Path, Path]:
        """Configure un TradingApp avec état interne mocké."""
        state_file = tmp_path / "state.json"
        stop_flag = tmp_path / "stop.flag"

        app = TradingApp()
        mock_config = MagicMock()
        mock_config.paths.state = str(state_file)
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
