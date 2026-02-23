"""Groupe de commandes CLI pour le trading live."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import click

from src.core.app import TradingApp
from src.core.config import load_app_config
from src.core.exceptions import ConfigError, ExchangeError, InsufficientBalanceError, LockError

__all__ = ["trade"]


@click.group()
def trade():
    """Commandes de trading live."""


@trade.command()
@click.option("--strategy", "-s", required=True, help="Nom de la stratégie à exécuter.")
@click.option("--min-balance", default=10.0, help="Balance minimale requise en USDT.")
@click.pass_context
def start(ctx, strategy, min_balance):
    """Démarre une stratégie de trading avec health check complet."""
    config_path = Path(ctx.obj["CONFIG_PATH"]) if ctx.obj.get("CONFIG_PATH") else None
    app = TradingApp()
    try:
        asyncio.run(app.run_live(strategy, config_path=config_path, min_balance=Decimal(str(min_balance))))
    except ConfigError as e:
        click.echo(f"❌ Erreur de configuration : {e}", err=True)
        raise SystemExit(1) from e
    except ExchangeError as e:
        click.echo(f"❌ Erreur exchange : {e}", err=True)
        raise SystemExit(1) from e
    except InsufficientBalanceError as e:
        click.echo(f"❌ Balance insuffisante : {e}", err=True)
        raise SystemExit(1) from e
    except LockError as e:
        click.echo(f"❌ Double instance détectée : {e}", err=True)
        raise SystemExit(1) from e
    except KeyboardInterrupt:
        click.echo("\n⏹ Arrêt demandé par l'utilisateur")


@trade.command()
@click.pass_context
def stop(ctx):
    """Envoie un signal d'arrêt au système de trading actif."""
    config_path = Path(ctx.obj["CONFIG_PATH"]) if ctx.obj.get("CONFIG_PATH") else None
    try:
        config = load_app_config(config_path)
        # Dériver data_dir depuis paths.state (ex: "data/state.json" → "data/")
        data_dir = Path(config.paths.state).parent
        stop_flag = data_dir / "stop.flag"
    except ConfigError:
        # Fallback si config non accessible
        stop_flag = Path("data/stop.flag")
    stop_flag.parent.mkdir(parents=True, exist_ok=True)
    stop_flag.touch()
    click.echo("⏹ Signal d'arrêt envoyé — le système va s'arrêter proprement")
