"""Compile les résultats de backtest RSI+HA en 3 configurations en un fichier de comparaison."""
import json
from pathlib import Path

BACKTEST_DIR = Path("data/backtest")
OUTPUT_FILE = BACKTEST_DIR / "rsi_ha_comparison.json"

FILES = {
    "fixed_percent": BACKTEST_DIR / "rsi_ha_fixed_percent.json",
    "martingale": BACKTEST_DIR / "rsi_ha_martingale.json",
    "martingale_inverse": BACKTEST_DIR / "rsi_ha_martingale_inverse.json",
}


def main() -> None:
    results = {}
    period_from: str | None = None
    period_to: str | None = None
    pair: str | None = None

    for mode, path in FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"Fichier manquant : {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        results[mode] = {"metrics": data["metrics"]}

        # Dériver la période et la paire depuis le premier fichier trouvé
        if period_from is None and "period_from" in data:
            period_from = data["period_from"]
        if period_to is None and "period_to" in data:
            period_to = data["period_to"]
        if pair is None and "pair" in data:
            pair = data["pair"]

    comparison = {
        "strategy": "rsi_ha",
        "period": {
            "from": period_from or "2024-01-01",
            "to": period_to or "2025-01-01",
        },
        "pair": pair or "BTC/USDT",
        "results": results,
    }

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print(f"Comparaison exportée → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
