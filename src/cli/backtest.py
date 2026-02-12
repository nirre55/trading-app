"""Groupe de commandes CLI pour le backtesting."""

import click

__all__ = ["backtest"]


@click.group()
def backtest():
    """Commandes de backtesting."""


@backtest.command()
@click.option("--strategy", "-s", required=True, help="Nom de la stratégie à backtester.")
def run(strategy):
    """Lance un backtest sur une stratégie."""
    click.echo(f"[placeholder] Backtest de la stratégie '{strategy}'...")
