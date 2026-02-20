"""Calcul des métriques de performance et export JSON des résultats backtest."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from src.models.trade import TradeResult

__all__ = ["BacktestMetrics", "BacktestResult", "MetricsCalculator"]


class BacktestMetrics(BaseModel):
    """Métriques agrégées d'un backtest (FR24)."""

    total_trades: int
    win_rate: float  # 0.0 à 1.0
    avg_rr: float  # avg(gains) / avg(|pertes|)
    max_drawdown: float  # déclin peak-to-trough en % capital initial
    max_consecutive_wins: int
    max_consecutive_losses: int
    profit_factor: float  # sum(gains) / sum(|pertes|), inf si 0 perte


class BacktestResult(BaseModel):
    """Résultats complets du backtest — métriques + liste de trades (FR26)."""

    metrics: BacktestMetrics
    trades: list[TradeResult]


class MetricsCalculator:
    """Calcule les métriques de performance et exporte les résultats en JSON.

    Usage :
        calculator = MetricsCalculator()
        result = calculator.compute(simulator.closed_trades)
        calculator.export_json(result, "data/backtest/2024-01-01.json")
    """

    def __init__(self) -> None:
        logger.debug("MetricsCalculator initialisé")

    def compute(self, trades: list[TradeResult]) -> BacktestResult:
        """Calcule les 7 métriques de performance (FR24)."""
        if not trades:
            return BacktestResult(
                metrics=BacktestMetrics(
                    total_trades=0,
                    win_rate=0.0,
                    avg_rr=0.0,
                    max_drawdown=0.0,
                    max_consecutive_wins=0,
                    max_consecutive_losses=0,
                    profit_factor=0.0,
                ),
                trades=[],
            )

        total_trades = len(trades)
        winning = [t for t in trades if t.pnl > Decimal("0")]
        losing = [t for t in trades if t.pnl < Decimal("0")]

        win_rate = len(winning) / total_trades

        avg_win: Decimal = (
            sum((t.pnl for t in winning), Decimal("0")) / len(winning)
            if winning
            else Decimal("0")
        )
        avg_loss: Decimal = (
            sum((abs(t.pnl) for t in losing), Decimal("0")) / len(losing)
            if losing
            else Decimal("0")
        )
        avg_rr = float(avg_win / avg_loss) if avg_loss > 0 else 0.0

        total_gains: Decimal = sum((t.pnl for t in winning), Decimal("0"))
        total_losses: Decimal = sum((abs(t.pnl) for t in losing), Decimal("0"))
        if total_losses > 0:
            profit_factor = float(total_gains / total_losses)
        elif total_gains > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # Drawdown peak-to-trough en % du capital initial
        initial_capital = trades[0].capital_before
        peak = Decimal("0")
        cumulative = Decimal("0")
        max_dd = Decimal("0")
        for trade in trades:
            cumulative += trade.pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = peak - cumulative
            if drawdown > max_dd:
                max_dd = drawdown
        max_drawdown = float(max_dd / initial_capital) if initial_capital > 0 else 0.0

        # Séries consécutives
        max_consec_wins = max_consec_losses = 0
        cur_wins = cur_losses = 0
        for trade in trades:
            if trade.pnl > Decimal("0"):
                cur_wins += 1
                cur_losses = 0
            elif trade.pnl < Decimal("0"):
                cur_losses += 1
                cur_wins = 0
            else:  # pnl == 0 — breakeven : casse les deux séries sans être ni gain ni perte
                cur_wins = 0
                cur_losses = 0
            max_consec_wins = max(max_consec_wins, cur_wins)
            max_consec_losses = max(max_consec_losses, cur_losses)

        logger.info(
            "Métriques calculées — {} trades, win_rate={:.1%}, profit_factor={:.2f}",
            total_trades,
            win_rate,
            profit_factor,
        )

        return BacktestResult(
            metrics=BacktestMetrics(
                total_trades=total_trades,
                win_rate=win_rate,
                avg_rr=avg_rr,
                max_drawdown=max_drawdown,
                max_consecutive_wins=max_consec_wins,
                max_consecutive_losses=max_consec_losses,
                profit_factor=profit_factor,
            ),
            trades=trades,
        )

    def export_json(self, result: BacktestResult, output_path: Path | str) -> None:
        """Exporte les résultats en JSON structuré (FR26, NFR14)."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        metrics_dict = result.metrics.model_dump()
        # ⚠️ CRITIQUE : json.dumps() lève ValueError pour float("inf") — non-JSON standard
        # Convertir les floats non-finis (inf, nan) en None (→ null en JSON)
        for key, val in metrics_dict.items():
            if isinstance(val, float) and not math.isfinite(val):
                metrics_dict[key] = None

        # Même convention que TradeLogger : Decimal→str, timedelta→float (NFR14)
        trades_list = []
        for trade in result.trades:
            record = trade.model_dump(mode="json")
            record["duration"] = trade.duration.total_seconds()
            trades_list.append(record)

        export_data = {"metrics": metrics_dict, "trades": trades_list}

        with open(output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        logger.info(
            "Résultats backtest exportés — fichier={} trades={}", output.resolve(), len(result.trades)
        )
