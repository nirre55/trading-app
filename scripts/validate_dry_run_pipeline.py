"""Script de validation E2E du pipeline dry-run — Story 11.3 AC2.

Objectif : valider le pipeline complet MockExecutor sans WebSocket live.
  WebSocket → (remplacé par injection directe) → Strategy → MockExecutor → JSONL + Telegram

Le testnet Bitget a des prix OHLCV figés (H=L=O=C) → SL invalide en live.
Ce script injecte des candles synthétiques avec variation de prix réaliste
pour exercer exactement le même code de production.

Usage :
    uv run python scripts/validate_dry_run_pipeline.py --config config/config.yaml

Résultats attendus :
    - Trade simulé ouvert (log [DRY-RUN] Trade simulé ouvert)
    - Fichier JSONL créé dans data/trades/ avec "dry_run": true
    - Notification Telegram reçue avec préfixe [DRY-RUN]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

# Ajouter le répertoire racine au path Python
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.capital.factory import create_capital_manager
from src.exchange.base import BaseExchangeConnector
from src.models.exchange import Balance, MarketRules
from src.core.config import load_app_config, load_strategy_by_name
from src.core.event_bus import EventBus
from src.core.logging import setup_logging
from src.core.state_machine import StateMachine
from src.models.config import AppConfig, StrategyConfig
from src.models.events import CandleEvent, EventType
from src.notifications.notification_service import NotificationService
from src.strategies.rsi_ha_strategy import RsiHaStrategy
from src.trading.mock_executor import MockExecutor
from src.trading.trade_logger import TradeLogger

# ── Paramètres des candles synthétiques ───────────────────────────────────────
# Séquence simulant un fort oversold suivi d'un retournement bullish HA
# Prix basés sur BTC/USDT réel (journée du 2026-03-12)
SYNTHETIC_CANDLES = [
    # Phase de baisse forte → RSI en zone oversold
    # (timestamp, open, high, low, close)
    (1_000_000_000_000, 72000.0, 72100.0, 71900.0, 71950.0),
    (1_000_000_060_000, 71950.0, 71960.0, 71600.0, 71650.0),
    (1_000_000_120_000, 71650.0, 71680.0, 71300.0, 71320.0),
    (1_000_000_180_000, 71320.0, 71340.0, 70900.0, 70950.0),
    (1_000_000_240_000, 70950.0, 70980.0, 70500.0, 70550.0),
    (1_000_000_300_000, 70550.0, 70580.0, 70200.0, 70220.0),
    (1_000_000_360_000, 70220.0, 70240.0, 69900.0, 69950.0),
    (1_000_000_420_000, 69950.0, 70000.0, 69700.0, 69720.0),
    # Candle de retournement bullish HA fort (close=72000, high=72500)
    # → HA_close(70930) > HA_open(70123) → BULLISH ✓
    # → SL = min(low C5-C9) = 69500 < entry 72000 → SL valide ✓
    (1_000_000_480_000, 69720.0, 72500.0, 69500.0, 72000.0),
    # Candle de clôture trade — TP hit (close=77500 > TP=77000)
    # → déclenche _close_simulated_trade → log JSONL avec dry_run=true
    (1_000_000_540_000, 72000.0, 78000.0, 71800.0, 77500.0),
    # Candle supplémentaire pour flush event bus
    (1_000_000_600_000, 77500.0, 77600.0, 77400.0, 77550.0),
]


def make_candle(row: tuple) -> CandleEvent:
    """Crée un CandleEvent à partir d'un tuple (ts, o, h, l, c)."""
    ts, o, h, l, c = row
    return CandleEvent(
        event_type=EventType.CANDLE_CLOSED,
        pair="BTC/USDT",
        timeframe="5m",
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal("1.0"),
    )


class _MockConnector:
    """Connecteur minimal pour le MockExecutor (fetch_balance uniquement)."""

    async def fetch_balance(self) -> Balance:
        """Simule une balance de 1000 USDT."""
        return Balance(free=Decimal("1000.0"), total=Decimal("1000.0"), used=Decimal("0.0"), currency="USDT")


async def run_pipeline_validation(config_path: str) -> bool:
    """Exécute la validation du pipeline dry-run avec candles synthétiques.

    Returns:
        True si tous les critères AC2 sont satisfaits, False sinon.
    """
    # ── Chargement config ──────────────────────────────────────────────────────
    config_file = Path(config_path)
    if not config_file.exists():
        print("[ERREUR] Fichier de configuration introuvable : %s" % config_path)
        print("         Utilisation : uv run python scripts/validate_dry_run_pipeline.py --config config/config.yaml")
        return False
    try:
        app_config: AppConfig = load_app_config(config_file)
        strategy_config: StrategyConfig = load_strategy_by_name("rsi_ha_strategy")
    except Exception as exc:
        print("[ERREUR] Echec chargement configuration : %s" % exc)
        return False
    setup_logging(app_config.defaults.log_level if app_config.defaults else "INFO")

    # ── Instanciation pipeline ─────────────────────────────────────────────────
    event_bus = EventBus()
    state_machine = StateMachine(
        event_bus=event_bus,
        strategy_name=strategy_config.name,
        pair=strategy_config.pair,
    )
    # Règles de marché réalistes pour BTC/USDT (Bitget testnet values)
    market_rules = MarketRules(
        step_size=Decimal("0.000001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("1.0"),
        max_leverage=1,
    )
    capital_manager = create_capital_manager(strategy_config.capital, market_rules)
    mock_connector = cast(BaseExchangeConnector, _MockConnector())

    trade_logger = TradeLogger(trades_dir=Path("data/trades"))

    # Notification Telegram (préfixe [DRY-RUN] automatique via dry_run=True)
    notification_service = NotificationService(app_config.telegram, dry_run=True)

    # Wiring notifications → bus (identique à app.py)
    async def _on_trade_opened_notify(event: Any) -> None:
        await notification_service.notify_trade_opened(event)

    event_bus.on(EventType.TRADE_OPENED, _on_trade_opened_notify)

    mock_executor = MockExecutor(
        connector=mock_connector,
        event_bus=event_bus,
        config=strategy_config,
        capital_manager=capital_manager,
        trade_logger=trade_logger,
    )

    strategy = RsiHaStrategy(
        config=strategy_config,
        state_machine=state_machine,
        event_bus=event_bus,
    )
    print("\n[VALIDATE] === Injection de %d candles synthetiques ===" % len(SYNTHETIC_CANDLES))

    # ── Injection des candles ──────────────────────────────────────────────────
    signal_fired = False
    trade_opened = False

    # Observer les trades ouverts
    async def on_trade_opened(event):  # type: ignore[type-arg]
        nonlocal trade_opened
        trade_opened = True
        print("[VALIDATE] Trade ouvert detecte : trade_id=%s" % getattr(event, "trade_id", "?"))

    event_bus.on(EventType.TRADE_OPENED, on_trade_opened)

    async def on_signal_long(event):  # type: ignore[type-arg]
        nonlocal signal_fired
        signal_fired = True
        print("[VALIDATE] Signal LONG recu : entry=%s sl=%s" % (
            getattr(event, "price", "?"),
            getattr(event, "sl_price", "?"),
        ))

    event_bus.on(EventType.STRATEGY_SIGNAL_LONG, on_signal_long)

    for i, row in enumerate(SYNTHETIC_CANDLES):
        candle = make_candle(row)
        print("[VALIDATE] Candle #%d : O=%.2f H=%.2f L=%.2f C=%.2f" % (
            i + 1, float(candle.open), float(candle.high), float(candle.low), float(candle.close)
        ))
        await event_bus.emit(EventType.CANDLE_CLOSED, candle)
        await asyncio.sleep(0.05)  # Laisser les handlers s'exécuter

    # Petite pause pour les handlers async
    await asyncio.sleep(1.0)

    # ── Vérification JSONL ─────────────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl_path = Path("data/trades") / f"{today}.jsonl"
    jsonl_ok = False
    trade_data = None

    if jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if lines:
            trade_data = json.loads(lines[-1])
            jsonl_ok = trade_data.get("dry_run") is True
            print("[VALIDATE] JSONL trouve : %s" % jsonl_path)
            print("[VALIDATE] dry_run=%s trade_id=%s" % (
                trade_data.get("dry_run"), trade_data.get("trade_id", "?")
            ))

    # ── Rapport final ──────────────────────────────────────────────────────────
    print("\n[VALIDATE] === Rapport AC2 ===")
    print("  Signal LONG fire       : %s" % ("OK" if signal_fired else "ECHEC"))
    print("  Trade simule ouvert    : %s" % ("OK" if trade_opened else "ECHEC"))
    print("  JSONL dry_run=true     : %s" % ("OK" if jsonl_ok else "ECHEC"))
    print("  Telegram               : verifier sur telephone (notification [DRY-RUN])")

    await mock_executor.stop()
    strategy.stop()

    success = signal_fired and trade_opened and jsonl_ok
    print("\n[VALIDATE] Resultat global : %s" % ("SUCCES AC2" if success else "ECHEC"))
    return success


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation pipeline dry-run Story 11.3 AC2")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    success = asyncio.run(run_pipeline_validation(args.config))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
