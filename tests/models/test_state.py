"""Tests pour les modèles d'état (recovery JSON round-trip critique)."""

from datetime import datetime, timezone

from src.models.state import AppState, StrategyState, StrategyStateEnum


class TestStrategyStateEnum:
    """Tests pour l'enum StrategyStateEnum."""

    def test_valeurs(self):
        assert StrategyStateEnum.IDLE == "IDLE"
        assert StrategyStateEnum.WATCHING == "WATCHING"
        assert StrategyStateEnum.SIGNAL_READY == "SIGNAL_READY"
        assert StrategyStateEnum.IN_TRADE == "IN_TRADE"

    def test_est_string(self):
        assert isinstance(StrategyStateEnum.IDLE, str)


class TestStrategyState:
    """Tests pour StrategyState."""

    def test_instanciation_minimale(self):
        state = StrategyState(state=StrategyStateEnum.IDLE)
        assert state.state == StrategyStateEnum.IDLE
        assert state.conditions_met == []
        assert state.last_condition_candle is None
        assert state.current_trade_id is None

    def test_instanciation_complete(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        state = StrategyState(
            state=StrategyStateEnum.IN_TRADE,
            conditions_met=[0, 1, 2],
            last_condition_candle=42,
            current_trade_id="trade-001",
            timestamp=ts,
        )
        assert state.state == StrategyStateEnum.IN_TRADE
        assert state.conditions_met == [0, 1, 2]
        assert state.last_condition_candle == 42
        assert state.current_trade_id == "trade-001"

    def test_timestamp_par_defaut_utc(self):
        state = StrategyState(state=StrategyStateEnum.IDLE)
        assert state.timestamp is not None
        assert state.timestamp.tzinfo is not None

    def test_json_round_trip(self):
        """CRITIQUE : test de round-trip JSON pour crash recovery."""
        ts = datetime(2026, 6, 15, 8, 30, 0, tzinfo=timezone.utc)
        original = StrategyState(
            state=StrategyStateEnum.WATCHING,
            conditions_met=[0, 1],
            last_condition_candle=10,
            current_trade_id=None,
            timestamp=ts,
        )
        json_str = original.model_dump_json()
        restored = StrategyState.model_validate_json(json_str)

        assert restored.state == original.state
        assert restored.conditions_met == original.conditions_met
        assert restored.last_condition_candle == original.last_condition_candle
        assert restored.current_trade_id == original.current_trade_id
        assert restored.timestamp == original.timestamp


class TestAppState:
    """Tests pour AppState."""

    def test_instanciation_minimale(self):
        state = AppState()
        assert state.strategy_states == {}
        assert state.active_trades == []
        assert state.last_candle_timestamp is None

    def test_instanciation_complete(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        strat_state = StrategyState(
            state=StrategyStateEnum.IN_TRADE,
            conditions_met=[0, 1, 2],
            current_trade_id="trade-001",
            timestamp=ts,
        )
        app_state = AppState(
            strategy_states={"ma_strategie": strat_state},
            active_trades=["trade-001"],
            last_candle_timestamp=ts,
            uptime_start=ts,
        )
        assert "ma_strategie" in app_state.strategy_states
        assert app_state.active_trades == ["trade-001"]
        assert app_state.last_candle_timestamp == ts

    def test_json_round_trip(self):
        """CRITIQUE : test de round-trip JSON pour crash recovery complet."""
        ts = datetime(2026, 6, 15, 8, 30, 0, tzinfo=timezone.utc)
        strat1 = StrategyState(
            state=StrategyStateEnum.IN_TRADE,
            conditions_met=[0, 1, 2],
            last_condition_candle=42,
            current_trade_id="trade-001",
            timestamp=ts,
        )
        strat2 = StrategyState(
            state=StrategyStateEnum.IDLE,
            timestamp=ts,
        )
        original = AppState(
            strategy_states={"strategie_btc": strat1, "strategie_eth": strat2},
            active_trades=["trade-001"],
            last_candle_timestamp=ts,
            uptime_start=ts,
        )

        json_str = original.model_dump_json()
        restored = AppState.model_validate_json(json_str)

        assert restored.strategy_states.keys() == original.strategy_states.keys()
        assert (
            restored.strategy_states["strategie_btc"].state
            == original.strategy_states["strategie_btc"].state
        )
        assert (
            restored.strategy_states["strategie_btc"].conditions_met
            == original.strategy_states["strategie_btc"].conditions_met
        )
        assert (
            restored.strategy_states["strategie_btc"].current_trade_id
            == original.strategy_states["strategie_btc"].current_trade_id
        )
        assert restored.active_trades == original.active_trades
        assert restored.last_candle_timestamp == original.last_candle_timestamp
        assert restored.uptime_start == original.uptime_start

    def test_json_round_trip_etat_vide(self):
        """Round-trip avec état vide (démarrage initial)."""
        original = AppState()
        json_str = original.model_dump_json()
        restored = AppState.model_validate_json(json_str)

        assert restored.strategy_states == {}
        assert restored.active_trades == []
        assert restored.last_candle_timestamp is None
