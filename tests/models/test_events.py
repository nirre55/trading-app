"""Tests pour les modèles d'événements."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.models.events import (
    AppEvent,
    BaseEvent,
    CandleEvent,
    ErrorEvent,
    EventType,
    ExchangeEvent,
    StrategyEvent,
    TradeEvent,
)


class TestEventType:
    """Tests pour l'enum EventType."""

    def test_tous_les_types_format_domaine_action(self):
        for event_type in EventType:
            parts = event_type.value.split(".")
            assert len(parts) == 2, f"{event_type} n'a pas le format domaine.action"

    def test_six_domaines(self):
        domaines = {et.value.split(".")[0] for et in EventType}
        assert domaines == {"app", "exchange", "candle", "strategy", "trade", "error"}

    def test_17_types_au_total(self):
        assert len(EventType) == 17

    def test_valeurs_specifiques(self):
        assert EventType.APP_STARTED == "app.started"
        assert EventType.TRADE_OPENED == "trade.opened"
        assert EventType.ERROR_CRITICAL == "error.critical"
        assert EventType.CANDLE_CLOSED == "candle.closed"

    def test_strenum_est_une_string(self):
        assert isinstance(EventType.APP_STARTED, str)


class TestBaseEvent:
    """Tests pour BaseEvent."""

    def test_instanciation_avec_timestamp_utc(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        event = BaseEvent(event_type=EventType.APP_STARTED, timestamp=ts)
        assert event.event_type == EventType.APP_STARTED
        assert event.timestamp == ts

    def test_timestamp_par_defaut_utc(self):
        event = BaseEvent(event_type=EventType.APP_STARTED)
        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None

    def test_timestamp_naive_rejete(self):
        with pytest.raises(ValidationError):
            BaseEvent(
                event_type=EventType.APP_STARTED,
                timestamp=datetime(2026, 1, 1, 12, 0, 0),
            )

    def test_serialisation_json(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        event = BaseEvent(event_type=EventType.APP_STARTED, timestamp=ts)
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["event_type"] == "app.started"
        assert "2026" in data["timestamp"]


class TestAppEvent:
    """Tests pour AppEvent."""

    def test_instanciation(self):
        event = AppEvent(event_type=EventType.APP_STARTED, reason="démarrage")
        assert event.reason == "démarrage"

    def test_cross_domain_rejete(self):
        with pytest.raises(ValidationError):
            AppEvent(event_type=EventType.TRADE_OPENED)

    def test_reason_optionnel(self):
        event = AppEvent(event_type=EventType.APP_STOPPED)
        assert event.reason is None

    def test_herite_base_event(self):
        assert issubclass(AppEvent, BaseEvent)

    def test_serialisation_json(self):
        event = AppEvent(event_type=EventType.APP_STARTED, reason="init")
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["reason"] == "init"


class TestExchangeEvent:
    """Tests pour ExchangeEvent."""

    def test_instanciation(self):
        event = ExchangeEvent(
            event_type=EventType.EXCHANGE_CONNECTED, exchange_name="binance"
        )
        assert event.exchange_name == "binance"

    def test_cross_domain_rejete(self):
        with pytest.raises(ValidationError):
            ExchangeEvent(event_type=EventType.APP_STARTED, exchange_name="binance")

    def test_serialisation_json(self):
        event = ExchangeEvent(
            event_type=EventType.EXCHANGE_DISCONNECTED,
            exchange_name="binance",
            details="timeout",
        )
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["exchange_name"] == "binance"
        assert data["details"] == "timeout"


class TestCandleEvent:
    """Tests pour CandleEvent."""

    def test_instanciation(self):
        event = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="BTC/USDT",
            timeframe="1h",
            open=Decimal("50000.00"),
            high=Decimal("51000.00"),
            low=Decimal("49000.00"),
            close=Decimal("50500.00"),
            volume=Decimal("1234.56"),
        )
        assert event.pair == "BTC/USDT"
        assert event.close == Decimal("50500.00")

    def test_serialisation_json(self):
        event = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair="ETH/USDT",
            timeframe="15m",
            open=Decimal("3000"),
            high=Decimal("3100"),
            low=Decimal("2900"),
            close=Decimal("3050"),
            volume=Decimal("500"),
        )
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["pair"] == "ETH/USDT"


class TestStrategyEvent:
    """Tests pour StrategyEvent."""

    def test_instanciation(self):
        event = StrategyEvent(
            event_type=EventType.STRATEGY_SIGNAL_LONG,
            strategy_name="ma_strategie",
            pair="BTC/USDT",
            condition_index=2,
        )
        assert event.strategy_name == "ma_strategie"
        assert event.condition_index == 2

    def test_champs_optionnels(self):
        event = StrategyEvent(
            event_type=EventType.STRATEGY_TIMEOUT,
            strategy_name="test",
            pair="ETH/USDT",
        )
        assert event.condition_index is None
        assert event.details is None


class TestTradeEvent:
    """Tests pour TradeEvent."""

    def test_instanciation(self):
        event = TradeEvent(
            event_type=EventType.TRADE_OPENED,
            trade_id="trade-001",
            pair="BTC/USDT",
        )
        assert event.trade_id == "trade-001"

    def test_serialisation_json(self):
        event = TradeEvent(
            event_type=EventType.TRADE_CLOSED,
            trade_id="trade-002",
            pair="ETH/USDT",
            details="TP atteint",
        )
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["trade_id"] == "trade-002"
        assert data["details"] == "TP atteint"


class TestErrorEvent:
    """Tests pour ErrorEvent."""

    def test_instanciation(self):
        event = ErrorEvent(
            event_type=EventType.ERROR_RECOVERABLE,
            error_type="ConnectionError",
            message="connexion perdue",
        )
        assert event.error_type == "ConnectionError"
        assert event.message == "connexion perdue"

    def test_cross_domain_rejete(self):
        with pytest.raises(ValidationError):
            ErrorEvent(
                event_type=EventType.APP_STARTED,
                error_type="FatalError",
                message="crash",
            )

    def test_traceback_optionnel(self):
        event = ErrorEvent(
            event_type=EventType.ERROR_CRITICAL,
            error_type="FatalError",
            message="crash",
        )
        assert event.traceback is None

    def test_serialisation_json(self):
        event = ErrorEvent(
            event_type=EventType.ERROR_RECOVERABLE,
            error_type="RateLimitError",
            message="429",
            traceback="Traceback...",
        )
        json_str = event.model_dump_json()
        data = json.loads(json_str)
        assert data["traceback"] == "Traceback..."
