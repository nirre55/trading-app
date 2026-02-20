"""Tests unitaires pour DataDownloader — téléchargement OHLCV, cache, pagination (AC7)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backtest.data_downloader import DataDownloader

# ── Constantes de test ────────────────────────────────────────────────────────

START_DT = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DT = datetime(2024, 1, 10, tzinfo=timezone.utc)
START_MS = int(START_DT.timestamp() * 1000)
END_MS = int(END_DT.timestamp() * 1000)

SAMPLE_CANDLES = [
    [START_MS + i * 3_600_000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]
    for i in range(5)
]

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "historical"


@pytest.fixture
def downloader(data_dir: Path) -> DataDownloader:
    return DataDownloader(data_dir)


@pytest.fixture
def mock_exchange() -> MagicMock:
    exchange = MagicMock()
    exchange.fetch_ohlcv = AsyncMock(return_value=SAMPLE_CANDLES)
    exchange.close = AsyncMock()
    return exchange


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_data_dir_auto_created(tmp_path: Path) -> None:
    """AC5 : DataDownloader crée le répertoire automatiquement à l'instanciation."""
    new_dir = tmp_path / "deep" / "nested" / "historical"
    assert not new_dir.exists()
    DataDownloader(new_dir)
    assert new_dir.exists()


def test_cache_path_structure(downloader: DataDownloader, data_dir: Path) -> None:
    """Vérifie la structure hiérarchique du chemin de cache (avec heure pour éviter les collisions)."""
    cache_path = downloader._get_cache_path("binance", "BTC/USDT", "1h", START_DT, END_DT)
    path_str = str(cache_path)
    assert "binance" in path_str
    assert "BTC_USDT" in path_str
    assert "1h" in path_str
    assert "2024-01-01T000000" in path_str  # format avec heure — évite collision si même date/heure différente
    assert "2024-01-10T000000" in path_str
    assert cache_path.suffix == ".json"


@pytest.mark.asyncio
async def test_download_calls_fetch_ohlcv(
    downloader: DataDownloader, mock_exchange: MagicMock
) -> None:
    """AC1 : download() appelle fetch_ohlcv avec les bons arguments (pair, timeframe, since, limit)."""
    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    mock_exchange.fetch_ohlcv.assert_awaited_once_with(
        "BTC/USDT", "1h", since=START_MS, limit=1000
    )
    assert len(candles) > 0


@pytest.mark.asyncio
async def test_download_saves_to_cache(
    downloader: DataDownloader, data_dir: Path, mock_exchange: MagicMock
) -> None:
    """AC2 : les données téléchargées sont sauvegardées dans un fichier JSON."""
    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    cache_files = list(data_dir.rglob("*.json"))
    assert len(cache_files) == 1
    saved = json.loads(cache_files[0].read_text(encoding="utf-8"))
    assert saved == candles


@pytest.mark.asyncio
async def test_cache_hit_no_fetch_call(
    downloader: DataDownloader, mock_exchange: MagicMock
) -> None:
    """AC3 : si le cache existe, aucun appel ccxt n'est effectué."""
    cache_path = downloader._get_cache_path("binance", "BTC/USDT", "1h", START_DT, END_DT)
    downloader._save_to_cache(cache_path, SAMPLE_CANDLES)

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)
        mock_ccxt.binance.assert_not_called()

    assert candles == SAMPLE_CANDLES


@pytest.mark.asyncio
async def test_pagination_multiple_batches(data_dir: Path) -> None:
    """AC4 : la pagination effectue plusieurs appels fetch_ohlcv pour les grandes plages.

    Scénario : plage de 60 jours (1440 bougies horaires) → batch1 de 1000 bougies
    remplit CANDLES_PER_REQUEST → la boucle continue → batch2 de 5 bougies (partiel) → arrêt.
    """
    # Plage large : 60 jours = ~1440 bougies horaires, > CANDLES_PER_REQUEST (1000)
    wide_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    wide_end = datetime(2024, 3, 1, tzinfo=timezone.utc)
    wide_start_ms = int(wide_start.timestamp() * 1000)
    wide_end_ms = int(wide_end.timestamp() * 1000)

    # batch1 : 1000 bougies horaires — toutes dans la plage, page complète → pagination continue
    batch1 = [
        [wide_start_ms + i * 3_600_000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]
        for i in range(1000)
    ]
    # batch2 : 5 bougies — page partielle → pagination s'arrête
    batch2 = [
        [wide_start_ms + (1000 + i) * 3_600_000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]
        for i in range(5)
    ]

    downloader = DataDownloader(data_dir)
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=[batch1, batch2])
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", wide_start, wide_end)

    assert mock_exchange.fetch_ohlcv.await_count == 2
    in_range = [c for c in batch1 + batch2 if c[0] < wide_end_ms]
    assert len(candles) == len(in_range)  # 1005 bougies
    # Vérifie que le 2ème appel utilise since = batch1[-1][0] + 1 (progression correcte)
    second_call = mock_exchange.fetch_ohlcv.call_args_list[1]
    assert second_call.kwargs["since"] == batch1[-1][0] + 1


@pytest.mark.asyncio
async def test_empty_batch_stops_pagination(downloader: DataDownloader) -> None:
    """Batch vide : la boucle s'arrête et retourne une liste vide."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=[])
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert candles == []
    assert mock_exchange.fetch_ohlcv.await_count == 1


@pytest.mark.asyncio
async def test_candles_filtered_to_date_range(downloader: DataDownloader) -> None:
    """Bougies après end_dt filtrées : toutes les bougies retournées ont c[0] < END_MS."""
    candle_at_end_ms = [END_MS, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]
    batch = SAMPLE_CANDLES + [candle_at_end_ms]

    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=batch)
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert all(c[0] < END_MS for c in candles)
    assert len(candles) == len(SAMPLE_CANDLES)  # bougie à END_MS exclue


@pytest.mark.asyncio
async def test_exchange_close_called_on_success(
    downloader: DataDownloader, mock_exchange: MagicMock
) -> None:
    """AC6 : exchange.close() est toujours appelé après un téléchargement réussi."""
    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    mock_exchange.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_exchange_close_called_on_error(downloader: DataDownloader) -> None:
    """AC6 : exchange.close() est appelé même si fetch_ohlcv lève une exception."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(side_effect=RuntimeError("connection error"))
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        with pytest.raises(RuntimeError, match="connection error"):
            await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    mock_exchange.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_download_uses_cache(
    downloader: DataDownloader, mock_exchange: MagicMock
) -> None:
    """AC2+AC3 : le second appel avec les mêmes params lit le cache (1 seul appel réseau)."""
    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles1 = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    # Le second appel doit lire le cache — aucun appel ccxt
    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt2:
        candles2 = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)
        mock_ccxt2.binance.assert_not_called()

    assert candles1 == candles2


# ── Nouveaux tests (corrections code review) ──────────────────────────────────


@pytest.mark.asyncio
async def test_naive_datetime_raises_value_error(downloader: DataDownloader) -> None:
    """M3 : datetime sans timezone lève ValueError avant tout appel réseau."""
    naive_start = datetime(2024, 1, 1)  # sans tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        await downloader.download("binance", "BTC/USDT", "1h", naive_start, END_DT)


@pytest.mark.asyncio
async def test_invalid_exchange_name_raises_attribute_error(downloader: DataDownloader) -> None:
    """M4 : exchange_name invalide → AttributeError se propage naturellement (sans appel réseau)."""
    with pytest.raises(AttributeError):
        await downloader.download("notarealexchange_xyz_impossible", "BTC/USDT", "1h", START_DT, END_DT)


@pytest.mark.asyncio
async def test_start_after_end_returns_empty(data_dir: Path) -> None:
    """M6 : start_dt >= end_dt → retourne [] sans appel fetch_ohlcv, sans cache sauvegardé."""
    downloader = DataDownloader(data_dir)
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=[])
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", END_DT, START_DT)  # dates inversées

    assert candles == []
    mock_exchange.fetch_ohlcv.assert_not_awaited()  # boucle ne s'exécute pas
    assert len(list(data_dir.rglob("*.json"))) == 0  # résultat vide non caché (H2)


@pytest.mark.asyncio
async def test_empty_result_not_cached(downloader: DataDownloader, data_dir: Path) -> None:
    """H2 : résultat vide non sauvegardé — évite le cache-poisoning."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=[])
    mock_exchange.close = AsyncMock()

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    assert candles == []
    assert len(list(data_dir.rglob("*.json"))) == 0  # aucun cache créé pour résultat vide


@pytest.mark.asyncio
async def test_corrupted_cache_triggers_redownload(
    downloader: DataDownloader, mock_exchange: MagicMock
) -> None:
    """M1 : cache JSON corrompu → suppression et re-téléchargement transparent."""
    cache_path = downloader._get_cache_path("binance", "BTC/USDT", "1h", START_DT, END_DT)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("json invalide {{{", encoding="utf-8")

    with patch("src.backtest.data_downloader.ccxt_async") as mock_ccxt:
        mock_ccxt.binance.return_value = mock_exchange
        candles = await downloader.download("binance", "BTC/USDT", "1h", START_DT, END_DT)

    mock_exchange.fetch_ohlcv.assert_awaited()
    assert len(candles) > 0
    assert not cache_path.with_suffix(".tmp").exists()  # fichier tmp nettoyé
