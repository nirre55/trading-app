"""Tests pour MetricsCalculator — métriques de performance et export JSON."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.backtest.metrics import MetricsCalculator
from src.models.trade import TradeDirection, TradeResult


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_trade(
    pnl: Decimal,
    capital_before: Decimal = Decimal("10000"),
    direction: TradeDirection = TradeDirection.LONG,
) -> TradeResult:
    """Fabrique un TradeResult minimal pour les tests."""
    capital_after = capital_before + pnl
    return TradeResult(
        trade_id="test-id",
        pair="BTC/USDT",
        direction=direction,
        entry_price=Decimal("40000"),
        exit_price=Decimal("42000"),
        stop_loss=Decimal("39000"),
        take_profit=Decimal("42000"),
        leverage=1,
        pnl=pnl,
        duration=timedelta(hours=1),
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        capital_before=capital_before,
        capital_after=capital_after,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calculator() -> MetricsCalculator:
    return MetricsCalculator()


@pytest.fixture
def set_a() -> list[TradeResult]:
    """Set A — 5 trades mixtes (W, L, W, L, W)."""
    return [
        make_trade(Decimal("100"), Decimal("10000")),
        make_trade(Decimal("-50"), Decimal("10100")),
        make_trade(Decimal("200"), Decimal("10050")),
        make_trade(Decimal("-30"), Decimal("10250")),
        make_trade(Decimal("150"), Decimal("10220")),
    ]


@pytest.fixture
def set_b() -> list[TradeResult]:
    """Set B — 5 trades pour séries consécutives (W, W, L, L, L)."""
    return [
        make_trade(Decimal("100"), Decimal("10000")),
        make_trade(Decimal("200"), Decimal("10100")),
        make_trade(Decimal("-50"), Decimal("10300")),
        make_trade(Decimal("-80"), Decimal("10250")),
        make_trade(Decimal("-40"), Decimal("10170")),
    ]


# ---------------------------------------------------------------------------
# Tests — liste vide
# ---------------------------------------------------------------------------


def test_compute_empty_trades_returns_zeros(calculator: MetricsCalculator) -> None:
    """Liste vide → toutes les métriques à 0."""
    result = calculator.compute([])

    assert result.metrics.total_trades == 0
    assert result.metrics.win_rate == 0.0
    assert result.metrics.avg_rr == 0.0
    assert result.metrics.max_drawdown == 0.0
    assert result.metrics.max_consecutive_wins == 0
    assert result.metrics.max_consecutive_losses == 0
    assert result.metrics.profit_factor == 0.0
    assert result.trades == []


# ---------------------------------------------------------------------------
# Tests — Set A
# ---------------------------------------------------------------------------


def test_compute_win_rate_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A — win_rate = 3/5 = 0.6."""
    result = calculator.compute(set_a)
    assert result.metrics.win_rate == pytest.approx(0.6)


def test_compute_avg_rr_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A — avg_rr = avg(gains) / avg(|pertes|) = 150.0 / 40.0 = 3.75."""
    result = calculator.compute(set_a)
    assert result.metrics.avg_rr == pytest.approx(3.75)


def test_compute_profit_factor_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A — profit_factor = 450 / 80 = 5.625."""
    result = calculator.compute(set_a)
    assert result.metrics.profit_factor == pytest.approx(5.625)


def test_compute_max_drawdown_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A — max_drawdown = 50 / 10000 = 0.005 (0.5 %)."""
    result = calculator.compute(set_a)
    assert result.metrics.max_drawdown == pytest.approx(0.005)


def test_compute_total_trades_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A — total_trades = 5."""
    result = calculator.compute(set_a)
    assert result.metrics.total_trades == 5


def test_compute_consecutive_set_a(
    calculator: MetricsCalculator, set_a: list[TradeResult]
) -> None:
    """Set A (W,L,W,L,W) — max_consecutive_wins = 1, max_consecutive_losses = 1."""
    result = calculator.compute(set_a)
    assert result.metrics.max_consecutive_wins == 1
    assert result.metrics.max_consecutive_losses == 1


# ---------------------------------------------------------------------------
# Tests — Set B
# ---------------------------------------------------------------------------


def test_compute_consecutive_set_b(
    calculator: MetricsCalculator, set_b: list[TradeResult]
) -> None:
    """Set B (W,W,L,L,L) — max_consecutive_wins = 2, max_consecutive_losses = 3."""
    result = calculator.compute(set_b)
    assert result.metrics.max_consecutive_wins == 2
    assert result.metrics.max_consecutive_losses == 3


def test_compute_profit_factor_set_b(
    calculator: MetricsCalculator, set_b: list[TradeResult]
) -> None:
    """Set B — profit_factor = 300 / 170 ≈ 1.7647."""
    result = calculator.compute(set_b)
    assert result.metrics.profit_factor == pytest.approx(300 / 170, rel=1e-4)


# ---------------------------------------------------------------------------
# Tests — cas limites
# ---------------------------------------------------------------------------


def test_compute_all_wins_profit_factor_inf(calculator: MetricsCalculator) -> None:
    """3 trades tous positifs → profit_factor = float("inf")."""
    trades = [
        make_trade(Decimal("100")),
        make_trade(Decimal("200")),
        make_trade(Decimal("50")),
    ]
    result = calculator.compute(trades)
    assert result.metrics.profit_factor == float("inf")
    assert result.metrics.avg_rr == 0.0
    assert result.metrics.max_consecutive_losses == 0


def test_compute_all_losses(calculator: MetricsCalculator) -> None:
    """3 trades tous négatifs → win_rate = 0.0, profit_factor = 0.0, max_consecutive_wins = 0."""
    trades = [
        make_trade(Decimal("-100")),
        make_trade(Decimal("-50")),
        make_trade(Decimal("-200")),
    ]
    result = calculator.compute(trades)
    assert result.metrics.win_rate == 0.0
    assert result.metrics.profit_factor == 0.0
    assert result.metrics.max_consecutive_wins == 0
    assert result.metrics.avg_rr == 0.0


def test_compute_breakeven_trade_not_counted_as_loss(
    calculator: MetricsCalculator,
) -> None:
    """Un trade breakeven (pnl=0) casse les séries mais n'est ni win ni loss."""
    trades = [
        make_trade(Decimal("100")),   # win  → cur_wins=1
        make_trade(Decimal("0")),     # even → réinitialise les deux compteurs
        make_trade(Decimal("-50")),   # loss → cur_losses=1
    ]
    result = calculator.compute(trades)
    assert result.metrics.max_consecutive_wins == 1
    assert result.metrics.max_consecutive_losses == 1
    assert result.metrics.win_rate == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Tests — export JSON
# ---------------------------------------------------------------------------


def test_export_json_creates_file(
    calculator: MetricsCalculator, set_a: list[TradeResult], tmp_path: Path
) -> None:
    """export_json() crée le fichier au chemin spécifié."""
    result = calculator.compute(set_a)
    output = tmp_path / "backtest.json"
    calculator.export_json(result, output)
    assert output.exists()


def test_export_json_structure(
    calculator: MetricsCalculator, set_a: list[TradeResult], tmp_path: Path
) -> None:
    """Le JSON exporté contient les clés "metrics" et "trades" à la racine."""
    result = calculator.compute(set_a)
    output = tmp_path / "backtest.json"
    calculator.export_json(result, output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert "metrics" in data
    assert "trades" in data
    assert "total_trades" in data["metrics"]
    assert data["metrics"]["total_trades"] == 5


def test_export_json_creates_parent_dir(
    calculator: MetricsCalculator, set_a: list[TradeResult], tmp_path: Path
) -> None:
    """export_json() crée automatiquement le répertoire parent si absent."""
    result = calculator.compute(set_a)
    nested = tmp_path / "sous" / "dossier" / "backtest.json"
    calculator.export_json(result, nested)
    assert nested.exists()


def test_export_json_duration_as_float(
    calculator: MetricsCalculator, set_a: list[TradeResult], tmp_path: Path
) -> None:
    """La durée dans les trades exportés est un float (total_seconds)."""
    result = calculator.compute(set_a)
    output = tmp_path / "backtest.json"
    calculator.export_json(result, output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["trades"]) > 0
    duration_val = data["trades"][0]["duration"]
    assert isinstance(duration_val, float)
    assert duration_val == pytest.approx(3600.0)


def test_export_json_inf_profit_factor_becomes_null(
    calculator: MetricsCalculator, tmp_path: Path
) -> None:
    """profit_factor=inf (tous gagnants) → null dans le JSON exporté."""
    trades = [make_trade(Decimal("100")), make_trade(Decimal("200"))]
    result = calculator.compute(trades)
    output = tmp_path / "inf_test.json"
    calculator.export_json(result, output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["metrics"]["profit_factor"] is None


def test_export_json_decimal_fields_as_strings(
    calculator: MetricsCalculator, set_a: list[TradeResult], tmp_path: Path
) -> None:
    """AC5 : les champs Decimal dans les trades sont sérialisés comme strings (NFR14)."""
    result = calculator.compute(set_a)
    output = tmp_path / "backtest.json"
    calculator.export_json(result, output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["trades"]) > 0
    first_trade = data["trades"][0]
    assert isinstance(first_trade["pnl"], str), "pnl doit être une string (Decimal→str)"
    assert isinstance(first_trade["entry_price"], str), "entry_price doit être une string"
    assert isinstance(first_trade["exit_price"], str), "exit_price doit être une string"
    assert isinstance(first_trade["capital_before"], str), "capital_before doit être une string"
    assert isinstance(first_trade["capital_after"], str), "capital_after doit être une string"
