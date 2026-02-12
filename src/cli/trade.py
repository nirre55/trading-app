"""Groupe de commandes CLI pour le trading live."""

import click

__all__ = ["trade"]


@click.group()
def trade():
    """Commandes de trading live."""


@trade.command()
@click.option("--strategy", "-s", required=True, help="Nom de la stratégie à exécuter.")
def start(strategy):
    """Démarre une stratégie de trading."""
    click.echo(f"[placeholder] Démarrage de la stratégie '{strategy}'...")


@trade.command()
def stop():
    """Arrête la stratégie de trading en cours."""
    click.echo("[placeholder] Arrêt de la stratégie en cours...")
