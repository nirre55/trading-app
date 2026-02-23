"""Configuration centralisée du logging avec loguru."""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

__all__ = ["setup_logging", "register_sensitive_values"]

_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(api_key|api_secret|password|secret|token)"
            r"""(\s*[=:]\s*['"]?)([^'"\s,;}\]&#]+)(['"]?)"""
        ),
        r"\1\2***\4",
    ),
]

_REGISTERED_SENSITIVE_VALUES: list[str] = []


def register_sensitive_values(*values: str) -> None:
    """Enregistre des valeurs sensibles à masquer dans tous les logs.

    Appeler après setup_logging() avec les valeurs brutes des clés API.
    Toute occurrence de ces valeurs dans un message de log sera remplacée par ***.

    Chaque appel REMPLACE la liste entière des valeurs enregistrées précédemment.
    Passer toutes les valeurs en un seul appel. Les valeurs vides ou de longueur
    inférieure à 4 caractères sont ignorées.

    Args:
        *values: Valeurs sensibles à masquer (api_key, api_secret, etc.).
    """
    global _REGISTERED_SENSITIVE_VALUES
    _REGISTERED_SENSITIVE_VALUES = [v for v in values if v and len(v) >= 4]


def _sanitize_message(message: str) -> str:
    """Applique les patterns regex pour masquer les valeurs sensibles.

    Args:
        message: Message de log brut.

    Returns:
        Message avec les valeurs sensibles remplacées par ***.
    """
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    for value in _REGISTERED_SENSITIVE_VALUES:
        message = message.replace(value, "***")
    return message


def _format_exception(record: Record) -> str:
    """Rend et sanitise le bloc exception du record si présent.

    Args:
        record: Enregistrement loguru contenant les métadonnées du message.

    Returns:
        Texte de l'exception sanitisé, ou chaîne vide si pas d'exception.
    """
    exc = record["exception"]
    if exc is None or exc.type is None:
        return ""
    lines = traceback.format_exception(exc.type, exc.value, exc.traceback)
    return _sanitize_message("".join(lines))


def _file_format(record: Record) -> str:
    """Format callable loguru pour les fichiers avec sanitisation.

    Args:
        record: Enregistrement loguru contenant les métadonnées du message.

    Returns:
        Chaîne de format loguru pour le sink fichier.
    """
    record["extra"]["scrubbed"] = _sanitize_message(record["message"])
    record["extra"]["scrubbed_exception"] = _format_exception(record)
    return (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} | {extra[scrubbed]}\n{extra[scrubbed_exception]}"
    )


def _console_format(record: Record) -> str:
    """Format callable loguru pour la console avec sanitisation et couleurs.

    Args:
        record: Enregistrement loguru contenant les métadonnées du message.

    Returns:
        Chaîne de format loguru pour le sink console.
    """
    record["extra"]["scrubbed"] = _sanitize_message(record["message"])
    record["extra"]["scrubbed_exception"] = _format_exception(record)
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[scrubbed]}\n{extra[scrubbed_exception]}"
    )


def setup_logging(log_level: str = "INFO", log_dir: str = "data/logs") -> None:
    """Configure le logging applicatif avec loguru.

    Crée un sink console (stderr) et un sink fichier avec rotation quotidienne.
    Les clés API et secrets sont automatiquement filtrés dans tous les sinks.

    Args:
        log_level: Niveau de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Répertoire de destination des fichiers de log.
    """
    global _REGISTERED_SENSITIVE_VALUES
    _REGISTERED_SENSITIVE_VALUES = []

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
