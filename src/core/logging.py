"""Configuration centralisée du logging avec loguru."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

__all__ = ["setup_logging"]

_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(api_key|api_secret|password|secret|token)"
            r"""(\s*[=:]\s*['"]?)([^'"\s,;}\]]+)(['"]?)"""
        ),
        r"\1\2***\4",
    ),
]


def _sanitize_message(message: str) -> str:
    """Applique les patterns regex pour masquer les valeurs sensibles.

    Args:
        message: Message de log brut.

    Returns:
        Message avec les valeurs sensibles remplacées par ***.
    """
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


def _file_format(record: Record) -> str:
    """Format callable loguru pour les fichiers avec sanitisation.

    Args:
        record: Enregistrement loguru contenant les métadonnées du message.

    Returns:
        Chaîne de format loguru pour le sink fichier.
    """
    record["extra"]["scrubbed"] = _sanitize_message(record["message"])
    return (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} | {extra[scrubbed]}\n{exception}"
    )


def _console_format(record: Record) -> str:
    """Format callable loguru pour la console avec sanitisation et couleurs.

    Args:
        record: Enregistrement loguru contenant les métadonnées du message.

    Returns:
        Chaîne de format loguru pour le sink console.
    """
    record["extra"]["scrubbed"] = _sanitize_message(record["message"])
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[scrubbed]}\n{exception}"
    )


def setup_logging(log_level: str = "INFO", log_dir: str = "data/logs") -> None:
    """Configure le logging applicatif avec loguru.

    Crée un sink console (stderr) et un sink fichier avec rotation quotidienne.
    Les clés API et secrets sont automatiquement filtrés dans tous les sinks.

    Args:
        log_level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Répertoire de destination des fichiers de log.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stderr,
        format=_console_format,
        level=log_level.upper(),
        colorize=True,
        diagnose=False,
        backtrace=True,
    )

    logger.add(
        str(log_path / "trading_{time:YYYY-MM-DD}.log"),
        format=_file_format,
        level=log_level.upper(),
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,
        diagnose=False,
        backtrace=True,
    )

    logger.info("Logging initialisé")
