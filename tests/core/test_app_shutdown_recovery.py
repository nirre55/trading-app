"""Tests du graceful shutdown et crash recovery (Story 6.6)."""

from __future__ import annotations

import asyncio
import signal as signal_module
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.app import TradingApp
from src.core.event_bus import EventBus
from src.core.state_manager import StateManager
from src.exchange.ccxt_connector import CcxtConnector
from src.models.events import EventType
from src.models.exchange import Balance, OrderSide, OrderType
from src.models.state import AppState


def _make_balance(free: Decimal = Decimal("100")) -> Balance:
    """Helper : crée une Balance valide."""
    return Balance(total=free, free=free, used=Decimal("0"), currency="USDT")


@pytest.fixture
def mock_connector() -> MagicMock:
    """Connecteur mocké avec méthodes exchange async."""
    connector = MagicMock(spec=CcxtConnector)
    connector.fetch_positions = AsyncMock(return_value=[])
    connector.fetch_open_orders = AsyncMock(return_value=[])
    connector.place_order = AsyncMock(return_value=MagicMock())
    return connector


@pytest.fixture
def state_manager_with_active_trade(tmp_path: Path) -> StateManager:
    """StateManager avec un trade actif pré-sauvegardé."""
    sm = StateManager(tmp_path / "state.json")
    state = AppState(active_trades=["trade-abc-123"])
    sm.save(state)
    return sm


class TestRunCrashRecovery:
    """Tests de run_crash_recovery() — AC4, AC5, AC6, AC7."""

    @pytest.mark.asyncio
    async def test_no_state_file_returns_none(self, tmp_path: Path) -> None:
        """AC7 : pas de state.json → retourne None sans appel exchange."""
        sm = StateManager(tmp_path / "no_state.json")
        connector = MagicMock(spec=CcxtConnector)
        connector.fetch_positions = AsyncMock(return_value=[])
        connector.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        result = await app.run_crash_recovery(connector, sm, "BTC/USDT")

        assert result is None
        connector.fetch_positions.assert_not_called()
        connector.fetch_open_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_active_trades_returns_none(self, tmp_path: Path) -> None:
        """AC7 : active_trades vide → retourne None sans appel exchange."""
        sm = StateManager(tmp_path / "state.json")
        sm.save(AppState(active_trades=[]))
        connector = MagicMock(spec=CcxtConnector)
        connector.fetch_positions = AsyncMock(return_value=[])
        connector.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        result = await app.run_crash_recovery(connector, sm, "BTC/USDT")

        assert result is None
        connector.fetch_positions.assert_not_called()
        connector.fetch_open_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_position_with_protection(
        self,
        mock_connector: MagicMock,
        state_manager_with_active_trade: StateManager,
    ) -> None:
        """AC4 : position + ordres SL présents → trade conservé, monitoring reprend."""
        mock_connector.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_connector.fetch_open_orders = AsyncMock(return_value=[
            {"type": "stop_market", "side": "sell", "stopPrice": 45000.0},
        ])

        app = TradingApp()
        result = await app.run_crash_recovery(
            mock_connector, state_manager_with_active_trade, "BTC/USDT"
        )

        assert result is not None
        assert "trade-abc-123" in result.active_trades
        mock_connector.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_position_without_protection_closes(
        self,
        mock_connector: MagicMock,
        state_manager_with_active_trade: StateManager,
    ) -> None:
        """AC5 : position sans SL → place_order(MARKET), trade_id supprimé."""
        mock_connector.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_connector.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        app.event_bus = EventBus()

        result = await app.run_crash_recovery(
            mock_connector, state_manager_with_active_trade, "BTC/USDT"
        )

        assert result is not None
        assert "trade-abc-123" not in result.active_trades
        mock_connector.place_order.assert_called_once()
        call_pos_args = mock_connector.place_order.call_args[0]
        assert call_pos_args[0] == OrderSide.SELL   # Long → SELL pour fermer
        assert call_pos_args[1] == OrderType.MARKET

    @pytest.mark.asyncio
    async def test_recovery_no_position_found(
        self,
        mock_connector: MagicMock,
        state_manager_with_active_trade: StateManager,
    ) -> None:
        """AC4 : position absente sur exchange → trade_id supprimé, 0 place_order."""
        mock_connector.fetch_positions = AsyncMock(return_value=[])
        mock_connector.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        result = await app.run_crash_recovery(
            mock_connector, state_manager_with_active_trade, "BTC/USDT"
        )

        assert result is not None
        assert "trade-abc-123" not in result.active_trades
        mock_connector.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_emits_error_critical_when_closing(
        self,
        mock_connector: MagicMock,
        state_manager_with_active_trade: StateManager,
    ) -> None:
        """AC5 : position sans SL → ERROR_CRITICAL émis sur le bus."""
        mock_connector.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_connector.fetch_open_orders = AsyncMock(return_value=[])

        event_bus = EventBus()
        critical_events: list = []

        async def handler(event) -> None:
            critical_events.append(event)

        event_bus.on(EventType.ERROR_CRITICAL, handler)

        app = TradingApp()
        app.event_bus = event_bus

        result = await app.run_crash_recovery(
            mock_connector, state_manager_with_active_trade, "BTC/USDT"
        )

        assert result is not None
        assert len(critical_events) == 1
        assert critical_events[0].event_type == EventType.ERROR_CRITICAL

    @pytest.mark.asyncio
    async def test_recovery_timeout_returns_partial_state(
        self,
        mock_connector: MagicMock,
        state_manager_with_active_trade: StateManager,
    ) -> None:
        """AC6 : asyncio.TimeoutError → retourne état partiel, logge erreur."""
        mock_timeout_cm = MagicMock()
        mock_timeout_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_timeout_cm.__aexit__ = AsyncMock(return_value=False)

        app = TradingApp()

        with patch("asyncio.timeout", return_value=mock_timeout_cm):
            result = await app.run_crash_recovery(
                mock_connector, state_manager_with_active_trade, "BTC/USDT"
            )

        assert result is not None
        assert "trade-abc-123" in result.active_trades  # État partiel préservé

    @pytest.mark.asyncio
    async def test_recovery_two_trades_position_closed_once(
        self,
        mock_connector: MagicMock,
        tmp_path: Path,
    ) -> None:
        """H2 fix : 2 trade_ids actifs, 1 position sans SL → place_order appelé UNE seule fois."""
        sm = StateManager(tmp_path / "state.json")
        sm.save(AppState(active_trades=["trade-A", "trade-B"]))

        mock_connector.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_connector.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        app.event_bus = EventBus()

        result = await app.run_crash_recovery(mock_connector, sm, "BTC/USDT")

        assert result is not None
        # place_order appelé UNE seule fois malgré 2 trade_ids (H2 fix — open_position hors loop)
        mock_connector.place_order.assert_called_once()
        assert "trade-A" not in result.active_trades
        assert "trade-B" not in result.active_trades


class TestGracefulShutdown:
    """Tests du graceful shutdown — AC1, AC3."""

    def _setup_app(self, tmp_path: Path) -> tuple:
        """Configure un TradingApp avec état interne mocké."""
        state_file = tmp_path / "state.json"
        stop_flag = tmp_path / "stop.flag"

        app = TradingApp()
        mock_config = MagicMock()
        mock_config.paths.state = str(state_file)
        mock_config.paths.logs = str(tmp_path / "logs")
        mock_config.paths.backup = str(tmp_path / "backups")
        mock_config.defaults.backup_interval_hours = 86400
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
    async def test_state_not_deleted_on_shutdown(self, tmp_path: Path) -> None:
        """AC3 : state.json est CONSERVÉ sur disque après arrêt normal (stop.flag)."""
        app, _bus, state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            assert state_file.exists(), "state.json doit exister pendant run_live()"

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)

        # CRITIQUE AC3 : state.json ne doit PAS être supprimé à l'arrêt
        assert state_file.exists(), "AC3 FAIL: state.json supprimé à l'arrêt — bug critique"

    @pytest.mark.asyncio
    async def test_signal_handler_registered(self, tmp_path: Path) -> None:
        """AC1 : signal handler SIGINT enregistré dans run_live() (FR41)."""
        app, _bus, _state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        registered_signals: list = []

        def mock_signal_fn(signum: int, handler: object) -> object:
            registered_signals.append(signum)
            return signal_module.SIG_DFL

        with patch.object(signal_module, "signal", side_effect=mock_signal_fn), \
             patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            live_task = asyncio.create_task(app.run_live("ma-strat"))
            await asyncio.sleep(0.05)

            stop_flag.touch()
            await asyncio.wait_for(live_task, timeout=3.0)

        # Sur Windows : SIGINT enregistré via signal.signal()
        if sys.platform == "win32":
            assert signal_module.SIGINT in registered_signals, \
                "SIGINT doit être enregistré sur Windows (FR41)"

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform == "win32", reason="Test POSIX (Linux/Mac) uniquement")
    async def test_signal_handler_posix_registered(self, tmp_path: Path) -> None:
        """AC1 : SIGTERM et SIGINT enregistrés via loop.add_signal_handler sur POSIX (FR41)."""
        app, _bus, _state_file, stop_flag = self._setup_app(tmp_path)
        mock_conn = self._mock_connector()

        registered_signals: list[int] = []

        def mock_add_signal_handler(signum: int, callback: object) -> None:
            registered_signals.append(signum)

        with patch("src.core.app.CcxtConnector", return_value=mock_conn), \
             patch.object(app, "start", new_callable=AsyncMock):
            loop = asyncio.get_running_loop()
            original = loop.add_signal_handler
            loop.add_signal_handler = mock_add_signal_handler  # type: ignore[method-assign]
            try:
                live_task = asyncio.create_task(app.run_live("ma-strat"))
                await asyncio.sleep(0.05)
                stop_flag.touch()
                await asyncio.wait_for(live_task, timeout=3.0)
            finally:
                loop.add_signal_handler = original  # type: ignore[method-assign]

        assert signal_module.SIGTERM in registered_signals, \
            "SIGTERM doit être enregistré sur POSIX (FR41)"
        assert signal_module.SIGINT in registered_signals, \
            "SIGINT doit être enregistré sur POSIX (FR41)"


class TestVerifyTpslOnShutdown:
    """Tests de _verify_tpsl_on_shutdown() — AC2."""

    @pytest.mark.asyncio
    async def test_no_active_trades_no_exchange_calls(self) -> None:
        """AC2 : aucun trade actif → retour immédiat sans appel exchange."""
        mock_conn = MagicMock(spec=CcxtConnector)
        mock_conn.fetch_positions = AsyncMock(return_value=[])
        mock_conn.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        await app._verify_tpsl_on_shutdown(mock_conn, AppState(active_trades=[]))

        mock_conn.fetch_positions.assert_not_called()
        mock_conn.fetch_open_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_trades_no_open_position_calls_exchange(self) -> None:
        """AC2 : trade actif + aucune position exchange → appels exchange effectués."""
        mock_conn = MagicMock(spec=CcxtConnector)
        mock_conn.fetch_positions = AsyncMock(return_value=[])
        mock_conn.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        await app._verify_tpsl_on_shutdown(mock_conn, AppState(active_trades=["trade-X"]))

        mock_conn.fetch_positions.assert_called_once()
        mock_conn.fetch_open_orders.assert_called_once()

    @pytest.mark.asyncio
    async def test_active_trades_position_with_tpsl_no_exception(self) -> None:
        """AC2 : position ouverte avec TP/SL → log succès, pas d'exception."""
        mock_conn = MagicMock(spec=CcxtConnector)
        mock_conn.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_conn.fetch_open_orders = AsyncMock(return_value=[
            {"type": "stop_market", "stopPrice": 45000.0},
        ])

        app = TradingApp()
        await app._verify_tpsl_on_shutdown(mock_conn, AppState(active_trades=["trade-X"]))

        mock_conn.fetch_positions.assert_called_once()
        mock_conn.fetch_open_orders.assert_called_once()

    @pytest.mark.asyncio
    async def test_active_trades_position_without_tpsl_no_exception(self) -> None:
        """AC2 : position ouverte sans TP/SL → log warning, pas d'exception levée."""
        mock_conn = MagicMock(spec=CcxtConnector)
        mock_conn.fetch_positions = AsyncMock(return_value=[
            {"symbol": "BTC/USDT", "side": "long", "contracts": 0.1},
        ])
        mock_conn.fetch_open_orders = AsyncMock(return_value=[])

        app = TradingApp()
        await app._verify_tpsl_on_shutdown(mock_conn, AppState(active_trades=["trade-X"]))

        mock_conn.fetch_positions.assert_called_once()
        mock_conn.fetch_open_orders.assert_called_once()

    @pytest.mark.asyncio
    async def test_exchange_error_does_not_propagate(self) -> None:
        """AC2 : erreur exchange loggée, jamais propagée (shutdown non-bloquant)."""
        mock_conn = MagicMock(spec=CcxtConnector)
        mock_conn.fetch_positions = AsyncMock(side_effect=RuntimeError("network error"))

        app = TradingApp()
        # Ne doit PAS lever d'exception — le shutdown continue quoi qu'il arrive
        await app._verify_tpsl_on_shutdown(mock_conn, AppState(active_trades=["trade-X"]))
