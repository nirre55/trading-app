"""Tests pour les modèles exchange."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.models.exchange import (
    Balance,
    MarketRules,
    OrderInfo,
    OrderSide,
    OrderStatus,
    OrderType,
)


class TestMarketRules:
    """Tests pour MarketRules."""

    def test_instanciation_valide(self):
        rules = MarketRules(
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
            max_leverage=125,
        )
        assert rules.step_size == Decimal("0.001")
        assert rules.tick_size == Decimal("0.01")
        assert rules.min_notional == Decimal("10.0")
        assert rules.max_leverage == 125

    def test_valeurs_en_decimal(self):
        rules = MarketRules(
            step_size=Decimal("0.00001"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("5.0"),
            max_leverage=50,
        )
        assert isinstance(rules.step_size, Decimal)
        assert isinstance(rules.tick_size, Decimal)
        assert isinstance(rules.min_notional, Decimal)

    def test_serialisation_json(self):
        rules = MarketRules(
            step_size=Decimal("0.001"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
            max_leverage=125,
        )
        json_str = rules.model_dump_json()
        data = json.loads(json_str)
        assert data["max_leverage"] == 125


class TestOrderEnums:
    """Tests pour les enums OrderSide, OrderType, OrderStatus."""

    def test_order_side_valeurs(self):
        assert OrderSide.BUY == "BUY"
        assert OrderSide.SELL == "SELL"

    def test_order_type_valeurs(self):
        assert OrderType.MARKET == "MARKET"
        assert OrderType.LIMIT == "LIMIT"
        assert OrderType.STOP_LOSS == "STOP_LOSS"
        assert OrderType.TAKE_PROFIT == "TAKE_PROFIT"

    def test_order_status_valeurs(self):
        assert OrderStatus.PENDING == "PENDING"
        assert OrderStatus.FILLED == "FILLED"
        assert OrderStatus.CANCELLED == "CANCELLED"
        assert OrderStatus.FAILED == "FAILED"

    def test_enums_sont_strings(self):
        assert isinstance(OrderSide.BUY, str)
        assert isinstance(OrderType.MARKET, str)
        assert isinstance(OrderStatus.PENDING, str)


class TestOrderInfo:
    """Tests pour OrderInfo."""

    def _valid_order_dict(self) -> dict:
        return {
            "id": "order-001",
            "pair": "BTC/USDT",
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "quantity": Decimal("0.01"),
            "status": OrderStatus.PENDING,
        }

    def test_instanciation_valide(self):
        order = OrderInfo(**self._valid_order_dict())
        assert order.id == "order-001"
        assert order.pair == "BTC/USDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET

    def test_price_optionnel(self):
        order = OrderInfo(**self._valid_order_dict())
        assert order.price is None

    def test_price_explicite(self):
        data = {**self._valid_order_dict(), "price": Decimal("50000.00")}
        order = OrderInfo(**data)
        assert order.price == Decimal("50000.00")

    def test_timestamp_par_defaut(self):
        order = OrderInfo(**self._valid_order_dict())
        assert order.timestamp is not None
        assert order.timestamp.tzinfo is not None

    def test_serialisation_json(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        order = OrderInfo(
            **self._valid_order_dict(),
            timestamp=ts,
        )
        json_str = order.model_dump_json()
        data = json.loads(json_str)
        assert data["id"] == "order-001"
        assert data["side"] == "BUY"
        assert data["order_type"] == "MARKET"


class TestBalance:
    """Tests pour Balance."""

    def test_instanciation_valide(self):
        balance = Balance(
            total=Decimal("1000.00"),
            free=Decimal("800.00"),
            used=Decimal("200.00"),
        )
        assert balance.total == Decimal("1000.00")
        assert balance.free == Decimal("800.00")
        assert balance.used == Decimal("200.00")

    def test_currency_par_defaut_usdt(self):
        balance = Balance(
            total=Decimal("100"),
            free=Decimal("100"),
            used=Decimal("0"),
        )
        assert balance.currency == "USDT"

    def test_currency_explicite(self):
        balance = Balance(
            total=Decimal("100"),
            free=Decimal("100"),
            used=Decimal("0"),
            currency="BTC",
        )
        assert balance.currency == "BTC"

    def test_total_egal_free_plus_used(self):
        balance = Balance(
            total=Decimal("1000.00"),
            free=Decimal("800.00"),
            used=Decimal("200.00"),
        )
        assert balance.total == balance.free + balance.used

    def test_balance_incoherente_raise_validation_error(self):
        with pytest.raises(ValidationError, match="total"):
            Balance(
                total=Decimal("9999"),
                free=Decimal("1"),
                used=Decimal("1"),
            )

    def test_serialisation_json(self):
        balance = Balance(
            total=Decimal("500"),
            free=Decimal("300"),
            used=Decimal("200"),
        )
        json_str = balance.model_dump_json()
        data = json.loads(json_str)
        assert data["currency"] == "USDT"
