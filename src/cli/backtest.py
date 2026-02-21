"""Groupe de commandes CLI pour le backtesting."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import click

from src.core.app import TradingApp
from src.core.exceptions import ConfigError, TradingAppError

__all__ = ["backtest"]


@click.group()
def backtest():
    """Commandes de backtesting."""


@backtest.command()
@click.option("--strategy", "-s", required=True, help="Nom de la stratégie à backtester.")
@click.option("--from", "from_date", required=True, help="Date de début (YYYY-MM-DD).")
@click.option("--to", "to_date", required=True, help="Date de fin (YYYY-MM-DD).")
@click.option("--output", "-o", default=None, help="Chemin pour exporter les résultats en JSON.")
@click.pass_context
def run(ctx, strategy, from_date, to_date, output):
    """Lance un backtest sur données historiques."""
    try:
        start_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        click.echo(f"❌ Format de date invalide (attendu YYYY-MM-DD) : {e}", err=True)
        raise SystemExit(2) from e
    config_path = Path(ctx.obj["CONFIG_PATH"]) if ctx.obj.get("CONFIG_PATH") else None
    output_path = Path(output) if output else None
    app = TradingApp()
    try:
        result = asyncio.run(
            app.run_backtest(strategy, start_dt, end_dt, output_path=output_path, config_path=config_path)
        )
    except ConfigError as e:
        click.echo(f"❌ Erreur de configuration : {e}", err=True)
        raise SystemExit(1) from e
    except TradingAppError as e:
        click.echo(f"❌ Erreur système : {e}", err=True)
        raise SystemExit(1) from e
    # Affichage des métriques
    m = result.metrics
    click.echo("\n📊 Résultats du backtest :")
    click.echo(f"  Trades total     : {m.total_trades}")
    click.echo(f"  Win rate         : {m.win_rate:.1%}")
    click.echo(f"  Ratio R:R moyen  : {m.avg_rr:.2f}")
    click.echo(f"  Max drawdown     : {m.max_drawdown:.2%}")
    click.echo(f"  Max gains consec : {m.max_consecutive_wins}")
    click.echo(f"  Max pertes consec: {m.max_consecutive_losses}")
    click.echo(f"  Profit factor    : {m.profit_factor:.3f}")
    if output_path:
        click.echo(f"\n💾 Résultats exportés → {output_path}")
