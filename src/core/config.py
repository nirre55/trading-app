"""Chargement et validation de la configuration YAML avec Pydantic."""

from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import ValidationError

from src.core.exceptions import ConfigError
from src.models.config import AppConfig, StrategyConfig

__all__ = [
    "load_yaml_file",
    "load_app_config",
    "load_strategy_config",
    "load_strategy_by_name",
]


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    """Charge un fichier YAML et retourne son contenu sous forme de dict.

    Args:
        file_path: Chemin vers le fichier YAML à charger.

    Returns:
        Contenu du fichier YAML sous forme de dictionnaire.

    Raises:
        ConfigError: Si le fichier est absent, vide ou contient du YAML invalide.
    """
    if not file_path.exists():
        logger.error("Fichier de configuration introuvable : {}", file_path)
        raise ConfigError(
            f"Fichier de configuration introuvable : {file_path}",
            context={"file_path": str(file_path)},
        )

    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error("Erreur de parsing YAML dans {} : {}", file_path, e)
        raise ConfigError(
            f"Erreur de parsing YAML dans {file_path} : {e}",
            context={"file_path": str(file_path)},
        ) from e
    except OSError as e:
        logger.error("Impossible de lire le fichier de configuration {} : {}", file_path, e)
        raise ConfigError(
            f"Impossible de lire le fichier de configuration {file_path} : {e}",
            context={"file_path": str(file_path)},
        ) from e

    if data is None:
        logger.error("Fichier de configuration vide : {}", file_path)
        raise ConfigError(
            f"Fichier de configuration vide : {file_path}",
            context={"file_path": str(file_path)},
        )

    if not isinstance(data, dict):
        logger.error("Le fichier YAML ne contient pas un mapping : {}", file_path)
        raise ConfigError(
            f"Le fichier YAML ne contient pas un mapping : {file_path}",
            context={"file_path": str(file_path)},
        )

    logger.debug("Fichier YAML chargé avec succès : {}", file_path)
    return data


def load_app_config(config_path: Path | None = None) -> AppConfig:
    """Charge la configuration globale de l'application depuis un fichier YAML.

    Args:
        config_path: Chemin vers le fichier config.yaml.
            Par défaut : config/config.yaml.

    Returns:
        Instance AppConfig validée par Pydantic.

    Raises:
        ConfigError: Si le fichier est absent, invalide ou échoue à la validation.
    """
    if config_path is None:
        config_path = Path("config/config.yaml")

    data = load_yaml_file(config_path)

    try:
        config = AppConfig(**data)
    except ValidationError as e:
        logger.error("Validation de la configuration échouée : {}", e)
        raise ConfigError(
            f"Validation de la configuration échouée dans {config_path} : {e}",
            context={"file_path": str(config_path)},
        ) from e

    logger.info("Configuration application chargée avec succès depuis {}", config_path)
    return config


def load_strategy_config(strategy_path: Path) -> StrategyConfig:
    """Charge la configuration d'une stratégie depuis un fichier YAML.

    Args:
        strategy_path: Chemin vers le fichier de stratégie YAML.

    Returns:
        Instance StrategyConfig validée par Pydantic.

    Raises:
        ConfigError: Si le fichier est absent, invalide ou échoue à la validation.
    """
    data = load_yaml_file(strategy_path)

    try:
        strategy = StrategyConfig(**data)
    except ValidationError as e:
        logger.error("Validation de la stratégie échouée : {}", e)
        raise ConfigError(
            f"Validation de la stratégie échouée dans {strategy_path} : {e}",
            context={"file_path": str(strategy_path)},
        ) from e

    logger.info("Configuration stratégie '{}' chargée depuis {}", strategy.name, strategy_path)
    return strategy


def load_strategy_by_name(
    strategy_name: str, strategies_dir: Path | None = None
) -> StrategyConfig:
    """Résout un nom de stratégie vers son fichier YAML et le charge.

    Args:
        strategy_name: Nom de la stratégie (sans extension).
        strategies_dir: Répertoire contenant les fichiers de stratégie.
            Par défaut : config/strategies/.

    Returns:
        Instance StrategyConfig validée par Pydantic.

    Raises:
        ConfigError: Si le fichier de stratégie est introuvable ou invalide.
    """
    if strategies_dir is None:
        strategies_dir = Path("config/strategies")

    strategy_path = strategies_dir / f"{strategy_name}.yaml"
    logger.debug("Résolution stratégie '{}' → {}", strategy_name, strategy_path)

    if not strategy_path.exists():
        logger.error("Stratégie '{}' introuvable dans {}", strategy_name, strategies_dir)
        raise ConfigError(
            f"Stratégie '{strategy_name}' introuvable : {strategy_path}",
            context={
                "strategy_name": strategy_name,
                "file_path": str(strategy_path),
            },
        )

    return load_strategy_config(strategy_path)
