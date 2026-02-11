"""Point d'entrée CLI Click pour trading-app."""

import click


@click.group()
def cli():
    """trading-app - Outil CLI de trading crypto futures."""
    pass


if __name__ == "__main__":
    cli()
