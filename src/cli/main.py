"""Point d'entrée CLI Click pour trading-app."""

import click

from src.cli.backtest import backtest
from src.cli.status import status
from src.cli.trade import trade

__all__ = ["cli"]


@click.group()
@click.option("--debug/--no-debug", default=False, help="Active le mode debug.")
@click.option("--config", "-c", default=None, help="Chemin vers le fichier de configuration.")
@click.pass_context
def cli(ctx, debug, config):
    """trading-app - Outil CLI de trading crypto futures."""
    ctx.ensure_object(dict)
    ctx.obj["DEBUG"] = debug
    ctx.obj["CONFIG_PATH"] = config


cli.add_command(trade)
cli.add_command(backtest)
cli.add_command(status)


if __name__ == "__main__":
    cli()
