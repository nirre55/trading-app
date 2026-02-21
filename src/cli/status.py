"""Commande CLI pour afficher le statut de l'application."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click

from src.core.config import load_app_config
from src.core.exceptions import ConfigError

__all__ = ["status"]


@click.command()
@click.pass_context
def status(ctx):
    """Affiche le statut de l'application (FR35)."""
    config_path = Path(ctx.obj["CONFIG_PATH"]) if ctx.obj.get("CONFIG_PATH") else None
    try:
        config = load_app_config(config_path)
        state_file = Path(config.paths.state)
    except ConfigError:
        state_file = Path("data/state.json")  # fallback

    if not state_file.exists():
        click.echo("ℹ️  Aucune session de trading active")
        return

    try:
        with open(state_file, encoding="utf-8") as f:
            state_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        click.echo(f"⚠️  Impossible de lire l'état : {e}", err=True)
        return

    try:
        uptime_start = datetime.fromisoformat(state_data.get("uptime_start", ""))
    except (ValueError, TypeError):
        click.echo("⚠️  Champ 'uptime_start' manquant ou invalide dans l'état", err=True)
        return
    uptime = datetime.now(timezone.utc) - uptime_start
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    click.echo("📊 Statut du système de trading :")
    click.echo(f"  Uptime           : {hours:02d}:{minutes:02d}:{seconds:02d}")
    active_trades = state_data.get("active_trades", [])
    click.echo(f"  Trades actifs    : {len(active_trades)} {active_trades}")
    strategy_states = state_data.get("strategy_states", {})
    if strategy_states:
        click.echo("  Stratégies :")
        for name, s in strategy_states.items():
            click.echo(f"    {name}: {s.get('state', 'UNKNOWN')}")
    else:
        click.echo("  Stratégies       : aucune")
