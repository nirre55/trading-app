"""Commande CLI pour afficher le statut de l'application."""

import click

__all__ = ["status"]


@click.command()
def status():
    """Affiche le statut de l'application."""
    click.echo("[placeholder] Statut de l'application...")
