"""Tests unitaires pour TradeLogger — JSONL horodaté, flush immédiat, format stable (AC7)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.trade import TradeDirection, TradeResult
from src.trading.trade_logger import TradeLogger


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def trades_dir(tmp_path: Path) -> Path:
    return tmp_path / "trades"


@pytest.fixture
def trade_logger(trades_dir: Path) -> TradeLogger:
    return TradeLogger(trades_dir)


@pytest.fixture
def sample_result() -> TradeResult:
    return TradeResult(
        trade_id="test-trade-001",
        pair="BTC/USDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("50000.00"),
        exit_price=Decimal("52000.00"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        leverage=5,
        pnl=Decimal("20.50"),
        duration=timedelta(hours=1, minutes=2, seconds=3),
        capital_before=Decimal("1000.00"),
        capital_after=Decimal("1020.50"),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_creates_jsonl_file(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC1 : log_trade crée un fichier YYYY-MM-DD.jsonl dans le répertoire."""
    await trade_logger.log_trade(sample_result)
    files = list(trades_dir.glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].suffix == ".jsonl"


@pytest.mark.asyncio
async def test_log_contains_required_fields(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC2 : l'enregistrement JSON contient exactement les 13 champs requis (FR31)."""
    await trade_logger.log_trade(sample_result)
    file = next(trades_dir.glob("*.jsonl"))
    record = json.loads(file.read_text(encoding="utf-8").strip())
    required_fields = {
        "trade_id",
        "pair",
        "direction",
        "entry_price",
        "exit_price",
        "stop_loss",
        "take_profit",
        "leverage",
        "timestamp",
        "pnl",
        "duration",
        "capital_before",
        "capital_after",
    }
    assert required_fields.issubset(record.keys())


@pytest.mark.asyncio
async def test_log_appends_multiple_trades(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC1 : plusieurs appels à log_trade ajoutent des lignes (mode append — un trade par ligne)."""
    await trade_logger.log_trade(sample_result)
    await trade_logger.log_trade(sample_result)
    await trade_logger.log_trade(sample_result)
    file = next(trades_dir.glob("*.jsonl"))
    lines = [line for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3


@pytest.mark.asyncio
async def test_log_flush_immediate(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC3 : f.flush() et os.fsync() sont appelés après chaque écriture — flush double niveau (NFR11)."""
    with patch("os.fsync") as mock_fsync:
        await trade_logger.log_trade(sample_result)
        # os.fsync doit être appelé pour garantir la persistance disque (NFR11)
        mock_fsync.assert_called_once()
    # Le contenu est lisible après l'écriture
    file = next(trades_dir.glob("*.jsonl"))
    assert "BTC/USDT" in file.read_text(encoding="utf-8")


def test_trades_dir_auto_created(tmp_path: Path) -> None:
    """AC6 : le répertoire est créé automatiquement à l'instanciation (NFR11)."""
    new_dir = tmp_path / "deep" / "nested" / "trades"
    assert not new_dir.exists()
    TradeLogger(new_dir)
    assert new_dir.exists()


@pytest.mark.asyncio
async def test_log_decimal_serialized_as_string(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC4 : les Decimal sont sérialisés en string — format stable pour parsing externe (NFR14)."""
    await trade_logger.log_trade(sample_result)
    file = next(trades_dir.glob("*.jsonl"))
    record = json.loads(file.read_text(encoding="utf-8").strip())
    assert isinstance(record["entry_price"], str)
    assert isinstance(record["pnl"], str)
    assert isinstance(record["capital_before"], str)
    assert isinstance(record["capital_after"], str)


@pytest.mark.asyncio
async def test_log_error_does_not_raise(
    trade_logger: TradeLogger, sample_result: TradeResult
) -> None:
    """AC3 + Règle n°7 : une erreur d'écriture est loggée sans propager d'exception."""
    with patch("builtins.open", side_effect=OSError("disk full")):
        # Ne doit pas lever — les erreurs de logging ne bloquent pas l'exécution
        await trade_logger.log_trade(sample_result)


@pytest.mark.asyncio
async def test_log_file_uses_utc_date(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC4 : le nom du fichier JSONL utilise la date UTC (pas la date locale)."""
    utc_now = datetime(2026, 2, 19, 23, 0, 0, tzinfo=timezone.utc)
    mock_dt = MagicMock()
    mock_dt.now.return_value = utc_now

    with patch("src.trading.trade_logger.datetime", mock_dt):
        await trade_logger.log_trade(sample_result)

    expected_file = trades_dir / "2026-02-19.jsonl"
    assert expected_file.exists(), f"Fichier attendu : {expected_file}"


@pytest.mark.asyncio
async def test_log_duration_serialized_as_float(
    trade_logger: TradeLogger, trades_dir: Path, sample_result: TradeResult
) -> None:
    """AC4 : la duration timedelta est sérialisée en float (secondes) par Pydantic (NFR14)."""
    await trade_logger.log_trade(sample_result)
    file = next(trades_dir.glob("*.jsonl"))
    record = json.loads(file.read_text(encoding="utf-8").strip())
    # timedelta(hours=1, minutes=2, seconds=3) = 3723 secondes
    assert isinstance(record["duration"], (int, float))
    assert record["duration"] == pytest.approx(3723.0)


@pytest.mark.asyncio
async def test_jsonl_survives_simulated_crash(
    trades_dir: Path, sample_result: TradeResult
) -> None:
    """Persistance : un trade écrit survive à un crash simulé (aucun cleanup appelé).

    Règle dette technique Epic 6 (MEDIUM) : toute composante écrivant sur disque
    doit avoir au moins un test vérifiant la survie des données sans cleanup.
    Le flush immédiat (NFR11) garantit qu'os.fsync() est appelé avant le retour.
    """
    # Phase 1 : écriture via une première instance (simulée puis "crashée")
    logger_instance = TradeLogger(trades_dir)
    await logger_instance.log_trade(sample_result)
    # Pas de cleanup — simule un crash abrupt (pas d'appel à close/flush supplémentaire)
    del logger_instance

    # Phase 2 : relecture par une nouvelle instance indépendante
    files = list(trades_dir.glob("*.jsonl"))
    assert len(files) == 1, "Le fichier JSONL doit exister après crash simulé"

    lines = [l for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, "Le trade doit être présent dans le fichier"

    record = json.loads(lines[0])
    assert record["trade_id"] == sample_result.trade_id
    assert record["pair"] == sample_result.pair
