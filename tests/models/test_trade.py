"""Tests pour les modèles de trade."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.models.trade import TradeDirection, TradeRecord, TradeResult, TradeStatus


class TestTradeDirection:
    """Tests pour l'enum TradeDirection."""

    def test_valeurs(self):
        assert TradeDirection.LONG == "LONG"
        assert TradeDirection.SHORT == "SHORT"

    def test_est_string(self):
        assert isinstance(TradeDirection.LONG, str)


class TestTradeStatus:
    """Tests pour l'enum TradeStatus."""

    def test_valeurs(self):
        assert TradeStatus.OPEN == "OPEN"
        assert TradeStatus.CLOSED == "CLOSED"
        assert TradeStatus.FAILED == "FAILED"


class TestTradeRecord:
    """Tests pour TradeRecord."""

    def _valid_trade_record_dict(self) -> dict:
        return {
            "id": "trade-001",
            "pair": "BTC/USDT",
            "direction": TradeDirection.LONG,
            "entry_price": Decimal("50000.00"),
            "stop_loss": Decimal("49000.00"),
            "take_profit": Decimal("52000.00"),
            "leverage": 5,
            "quantity": Decimal("0.01"),
            "status": TradeStatus.OPEN,
            "capital_before": Decimal("1000.00"),
        }

    def test_instanciation_valide(self):
        record = TradeRecord(**self._valid_trade_record_dict())
        assert record.id == "trade-001"
        assert record.pair == "BTC/USDT"
        assert record.direction == TradeDirection.LONG
        assert record.leverage == 5

    def test_prix_en_decimal(self):
        record = TradeRecord(**self._valid_trade_record_dict())
        assert isinstance(record.entry_price, Decimal)
        assert isinstance(record.stop_loss, Decimal)
        assert isinstance(record.take_profit, Decimal)
        assert isinstance(record.quantity, Decimal)
        assert isinstance(record.capital_before, Decimal)

    def test_exit_price_optionnel(self):
        record = TradeRecord(**self._valid_trade_record_dict())
        assert record.exit_price is None

    def test_exit_price_explicite(self):
        data = {**self._valid_trade_record_dict(), "exit_price": Decimal("51000.00")}
        record = TradeRecord(**data)
        assert record.exit_price == Decimal("51000.00")

    def test_timestamp_par_defaut(self):
        record = TradeRecord(**self._valid_trade_record_dict())
        assert record.timestamp is not None
        assert record.timestamp.tzinfo is not None

    def test_serialisation_json(self):
        record = TradeRecord(**self._valid_trade_record_dict())
        json_str = record.model_dump_json()
        data = json.loads(json_str)
        assert data["id"] == "trade-001"
        assert data["pair"] == "BTC/USDT"
        assert data["direction"] == "LONG"
        # Decimal sérialisé en string en JSON
        assert "50000" in data["entry_price"]

    def test_json_round_trip(self):
        """Round-trip JSON pour persistance JSONL."""
        ts = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        original = TradeRecord(
            **{**self._valid_trade_record_dict(), "timestamp": ts}
        )
        json_str = original.model_dump_json()
        restored = TradeRecord.model_validate_json(json_str)

        assert restored.id == original.id
        assert restored.pair == original.pair
        assert restored.direction == original.direction
        assert restored.entry_price == original.entry_price
        assert restored.stop_loss == original.stop_loss
        assert restored.take_profit == original.take_profit
        assert restored.leverage == original.leverage
        assert restored.quantity == original.quantity
        assert restored.status == original.status
        assert restored.capital_before == original.capital_before
        assert restored.timestamp == original.timestamp


class TestTradeResult:
    """Tests pour TradeResult."""

    def _valid_trade_result_dict(self) -> dict:
        return {
            "trade_id": "trade-001",
            "pair": "BTC/USDT",
            "direction": TradeDirection.LONG,
            "entry_price": Decimal("50000.00"),
            "exit_price": Decimal("51000.00"),
            "stop_loss": Decimal("49000.00"),
            "take_profit": Decimal("52000.00"),
            "leverage": 5,
            "pnl": Decimal("100.00"),
            "duration": timedelta(hours=2, minutes=30),
            "timestamp": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "capital_before": Decimal("1000.00"),
            "capital_after": Decimal("1100.00"),
        }

    def test_instanciation_valide(self):
        result = TradeResult(**self._valid_trade_result_dict())
        assert result.trade_id == "trade-001"
        assert result.pnl == Decimal("100.00")
        assert result.duration == timedelta(hours=2, minutes=30)

    def test_capital_apres_trade(self):
        result = TradeResult(**self._valid_trade_result_dict())
        assert result.capital_before == Decimal("1000.00")
        assert result.capital_after == Decimal("1100.00")

    def test_serialisation_json(self):
        result = TradeResult(**self._valid_trade_result_dict())
        json_str = result.model_dump_json()
        data = json.loads(json_str)
        assert data["trade_id"] == "trade-001"
        assert "100" in data["pnl"]

    def test_duration_serialisation(self):
        result = TradeResult(**self._valid_trade_result_dict())
        json_str = result.model_dump_json()
        data = json.loads(json_str)
        # timedelta sérialisé en string ISO 8601 par Pydantic v2
        assert "duration" in data

    def test_json_round_trip(self):
        """Round-trip JSON pour persistance JSONL."""
        original = TradeResult(**self._valid_trade_result_dict())
        json_str = original.model_dump_json()
        restored = TradeResult.model_validate_json(json_str)

        assert restored.trade_id == original.trade_id
        assert restored.pair == original.pair
        assert restored.direction == original.direction
        assert restored.entry_price == original.entry_price
        assert restored.exit_price == original.exit_price
        assert restored.pnl == original.pnl
        assert restored.duration == original.duration
        assert restored.timestamp == original.timestamp
        assert restored.capital_before == original.capital_before
        assert restored.capital_after == original.capital_after
