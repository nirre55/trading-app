"""
Test de connexion Bitget Testnet — Validation du CcxtConnector.

Valide séquentiellement : connexion, règles de marché, balance,
positions et déconnexion. Affiche un résumé pass/fail.

Usage :
    uv run python scripts/test_bitget_connection.py
    uv run python scripts/test_bitget_connection.py --config config/config.testnet.yaml
    uv run python scripts/test_bitget_connection.py --pair BTC/USDT:USDT

Prérequis :
    Créer config/config.testnet.yaml à partir de config/config.testnet.yaml.example
    et renseigner les clés API Bitget testnet.

Paires Bitget CCXT (futures USDT-margined) :
    BTC/USDT:USDT   — Perpetuel BTC (défaut)
    ETH/USDT:USDT   — Perpetuel ETH
    SOL/USDT:USDT   — Perpetuel SOL

Critères de succès :
    ✅ Connexion établie et sandbox activé
    ✅ Règles de marché récupérées (step_size, tick_size, max_leverage)
    ✅ Balance USDT accessible (total >= 0)
    ✅ Positions ouvertes récupérées (liste, peut être vide)
    ✅ Déconnexion propre
"""

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import yaml
from loguru import logger
from pydantic import SecretStr

# Rendre les modules src/ accessibles depuis la racine du projet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.event_bus import EventBus  # noqa: E402
from src.core.exceptions import ExchangeConnectionError, ExchangeError  # noqa: E402
from src.exchange.ccxt_connector import CcxtConnector  # noqa: E402
from src.models.config import AppConfig, DefaultsConfig, ExchangeConfig, PathsConfig  # noqa: E402

# ── Constantes ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = Path("config/config.testnet.yaml")
DEFAULT_PAIR = "BTC/USDT:USDT"
DEFAULT_TIMEFRAME = "1h"
SEP = "=" * 60


# ── Chargement config ─────────────────────────────────────────────────────────


def load_config(config_path: Path) -> AppConfig:
    """Charge et valide la configuration depuis un fichier YAML."""
    if not config_path.exists():
        print(f"\n❌  Fichier de config introuvable : {config_path}")
        print("    → Copier config/config.testnet.yaml.example vers config/config.testnet.yaml")
        print("    → Renseigner les clés API Bitget testnet\n")
        sys.exit(1)

    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    exc_raw = raw["exchange"]
    password_raw = exc_raw.get("password")

    return AppConfig(
        exchange=ExchangeConfig(
            name=exc_raw["name"],
            api_key=SecretStr(exc_raw["api_key"]),
            api_secret=SecretStr(exc_raw["api_secret"]),
            password=SecretStr(password_raw) if password_raw else None,
            testnet=bool(exc_raw.get("testnet", True)),
        ),
        paths=PathsConfig(**raw["paths"]),
        defaults=DefaultsConfig(**raw.get("defaults", {})),
    )


# ── Helpers d'affichage ───────────────────────────────────────────────────────


def _ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"    ✅ {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"    ❌ {label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"    ⚠️  {label}{suffix}")


# ── Tests ─────────────────────────────────────────────────────────────────────


async def run_tests(config: AppConfig, pair: str) -> int:
    """Execute tous les tests de connexion. Retourne le nombre d'échecs."""
    failures = 0

    # ── En-tête ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  BITGET TESTNET — Validation CcxtConnector")
    print(f"  Exchange  : {config.exchange.name}")
    print(f"  Testnet   : {config.exchange.testnet}")
    print(f"  Paire     : {pair}")
    print(f"  Timeframe : {DEFAULT_TIMEFRAME}")
    print(f"{SEP}")

    if not config.exchange.testnet:
        print("\n  ⚠️  ATTENTION : testnet=false — connexion LIVE")

    if config.exchange.name.lower() != "bitget":
        print(f"\n  ⚠️  Exchange : {config.exchange.name} (ce script cible Bitget)")

    # ── Instanciation ─────────────────────────────────────────────────────────
    event_bus = EventBus()
    connector = CcxtConnector(
        exchange_config=config.exchange,
        event_bus=event_bus,
        pair=pair,
        timeframe=DEFAULT_TIMEFRAME,
    )

    # ── Test 1 : Connexion ────────────────────────────────────────────────────
    print("\n▶  Test 1 — Connexion")
    try:
        await connector.connect()
        _ok("connect() établie")
        if config.exchange.testnet:
            _ok("Sandbox Bitget activé")
    except ExchangeConnectionError as exc:
        _fail("connect()", str(exc))
        failures += 1
        print(f"\n{SEP}")
        print("  ❌ Connexion impossible — tests suivants ignorés.")
        print(f"{SEP}\n")
        return failures
    except ExchangeError as exc:
        _fail("connect()", str(exc))
        failures += 1
        print(f"\n{SEP}")
        print("  ❌ Erreur exchange — tests suivants ignorés.")
        print(f"{SEP}\n")
        return failures

    # ── Test 2 : Règles de marché ─────────────────────────────────────────────
    print("\n▶  Test 2 — Règles de marché")
    try:
        rules = connector.market_rules
        if rules is None:
            _fail("market_rules non nul", "None après connect()")
            failures += 1
        else:
            _ok("market_rules chargées")
            step_ok = rules.step_size > Decimal("0")
            tick_ok = rules.tick_size > Decimal("0")
            lev_ok = rules.max_leverage >= 1

            if step_ok:
                _ok(f"step_size = {rules.step_size}")
            else:
                _fail("step_size", f"valeur inattendue : {rules.step_size}")
                failures += 1

            if tick_ok:
                _ok(f"tick_size = {rules.tick_size}")
            else:
                _fail("tick_size", f"valeur inattendue : {rules.tick_size}")
                failures += 1

            if lev_ok:
                _ok(f"max_leverage = {rules.max_leverage}x")
            else:
                _fail("max_leverage", f"valeur inattendue : {rules.max_leverage}")
                failures += 1

            _ok(f"min_notional = {rules.min_notional} USDT")
    except Exception as exc:
        _fail("market_rules", str(exc))
        failures += 1

    # ── Test 3 : Balance ──────────────────────────────────────────────────────
    print("\n▶  Test 3 — Balance USDT")
    try:
        balance = await connector.fetch_balance()
        _ok("fetch_balance() réussi")
        if balance.total >= Decimal("0"):
            _ok(f"Balance totale = {balance.total} USDT")
        else:
            _fail("Balance totale", f"valeur négative : {balance.total}")
            failures += 1
        _ok(f"Balance libre  = {balance.free} USDT")
        _ok(f"Balance utilisée = {balance.used} USDT")
    except (ExchangeError, ExchangeConnectionError) as exc:
        _fail("fetch_balance()", str(exc))
        failures += 1

    # ── Test 4 : Positions ────────────────────────────────────────────────────
    print("\n▶  Test 4 — Positions ouvertes")
    try:
        positions = await connector.fetch_positions()
        _ok("fetch_positions() réussi")
        if positions:
            _ok(f"{len(positions)} position(s) ouverte(s) trouvée(s)")
        else:
            _ok("Aucune position ouverte (liste vide — normal sur testnet neuf)")
    except (ExchangeError, ExchangeConnectionError) as exc:
        _fail("fetch_positions()", str(exc))
        failures += 1

    # ── Test 5 : Déconnexion ──────────────────────────────────────────────────
    print("\n▶  Test 5 — Déconnexion")
    try:
        await connector.disconnect()
        _ok("disconnect() propre")
    except Exception as exc:
        _fail("disconnect()", str(exc))
        failures += 1

    # ── Résumé ────────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    if failures == 0:
        print("  ✅ TOUS LES TESTS RÉUSSIS — CcxtConnector valide sur Bitget testnet")
    else:
        print(f"  ❌ {failures} TEST(S) ÉCHOUÉ(S) — voir détails ci-dessus")
    print(f"{SEP}\n")

    return failures


# ── Point d'entrée ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validation du CcxtConnector contre Bitget testnet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  uv run python scripts/test_bitget_connection.py\n"
            "  uv run python scripts/test_bitget_connection.py --config config/config.testnet.yaml\n"
            "  uv run python scripts/test_bitget_connection.py --pair ETH/USDT:USDT\n"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Chemin vers la config YAML (défaut : {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--pair",
        default=DEFAULT_PAIR,
        help=f"Paire CCXT à tester (défaut : {DEFAULT_PAIR})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Désactive les logs Loguru (garde uniquement la sortie du script)",
    )
    args = parser.parse_args()

    if args.quiet:
        logger.remove()

    config = load_config(args.config)
    failures = asyncio.run(run_tests(config, args.pair))
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
