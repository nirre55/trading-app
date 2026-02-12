"""Tests pour l'orchestrateur principal TradingApp."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.core.app import TradingApp
from src.core.event_bus import EventBus
from src.core.exceptions import ConfigError
from src.models.events import AppEvent, EventType


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
