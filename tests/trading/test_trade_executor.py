"""Tests unitaires pour TradeExecutor — séquence atomique et invariant SL (NFR10)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.event_bus import EventBus
from src.core.exceptions import OrderFailedError
from src.exchange.base import BaseExchangeConnector
from src.models.events import EventType
from src.models.exchange import OrderInfo, OrderSide, OrderStatus, OrderType
from src.models.trade import TradeDirection, TradeStatus
from src.trading.trade_executor import TradeExecutor


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_order(
    order_id: str = "ord-123",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    price: Decimal = Decimal("50000"),
    quantity: Decimal = Decimal("0.01"),
    status: OrderStatus = OrderStatus.FILLED,
    pair: str = "BTC/USDT",
) -> OrderInfo:
    return OrderInfo(
        id=order_id,
        pair=pair,
        side=side,
        order_type=order_type,
        price=price,
        quantity=quantity,
        status=status,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def mock_connector() -> MagicMock:
    connector = MagicMock(spec=BaseExchangeConnector)
    # Comportement par défaut : entrée FILLED, SL PENDING
    connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        ]
    )
    connector.fetch_positions = AsyncMock(return_value=[])
    return connector


@pytest.fixture
def executor(mock_connector: MagicMock, event_bus: EventBus) -> TradeExecutor:
    return TradeExecutor(connector=mock_connector, event_bus=event_bus)


# ── Paramètres communs ────────────────────────────────────────────────────────


COMMON_PARAMS = {
    "pair": "BTC/USDT",
    "direction": TradeDirection.LONG,
    "quantity": Decimal("0.01"),
    "sl_price": Decimal("49000"),
    "capital_before": Decimal("1000"),
}


# ── Tests AC1 + AC5 — Scénarios succès ───────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_success_returns_trade_record(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC1 + AC5 : séquence atomique succès → TradeRecord OPEN."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert result.status == TradeStatus.OPEN
    assert result.stop_loss == Decimal("49000")
    assert result.take_profit == Decimal(0)  # placeholder Story 4.2


@pytest.mark.asyncio
async def test_atomic_trade_success_emits_trade_opened(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC5 : séquence succès → événement TRADE_OPENED émis avec bon trade_id."""
    received_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        received_events.append(event)

    event_bus.on(EventType.TRADE_OPENED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.TRADE_OPENED
    assert received_events[0].trade_id == result.id
    assert received_events[0].pair == "BTC/USDT"


@pytest.mark.asyncio
async def test_atomic_trade_success_trade_record_fields(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC1 : vérification des champs du TradeRecord (direction, pair, quantity, entry_price)."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED, price=Decimal("50500")),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is not None
    assert result.pair == "BTC/USDT"
    assert result.direction == TradeDirection.LONG
    assert result.quantity == Decimal("0.01")
    assert result.entry_price == Decimal("50500")
    assert result.capital_before == Decimal("1000")
    assert result.leverage == 1


# ── Tests AC2 — SL exception ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_sl_exception_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC2 : SL lève exception → position fermée immédiatement (3 appels place_order)."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),          # entry OK
            OrderFailedError("SL impossible"),               # SL lève exception
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),  # fermeture
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


@pytest.mark.asyncio
async def test_atomic_trade_sl_exception_emits_trade_failed(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC4 : SL exception → événement TRADE_FAILED émis."""
    received_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        received_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            OrderFailedError("SL impossible"),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(received_events) == 1
    assert received_events[0].event_type == EventType.TRADE_FAILED
    assert received_events[0].pair == "BTC/USDT"


# ── Tests AC3 — SL statut FAILED/CANCELLED ────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_sl_failed_status_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC3 : SL retourne statut FAILED → position fermée."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.FAILED),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


@pytest.mark.asyncio
async def test_atomic_trade_sl_cancelled_status_closes_position(
    executor: TradeExecutor, mock_connector: MagicMock
) -> None:
    """AC3 : SL retourne statut CANCELLED → position fermée."""
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),
            make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.CANCELLED),
            make_order(side=OrderSide.SELL, order_type=OrderType.MARKET),
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 3


# ── Tests entrée échoue ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_entry_failure_no_close_attempt(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """Si l'entrée retourne FAILED, aucun ordre de fermeture n'est tenté (1 seul appel).

    AC4 : TRADE_FAILED est quand même émis — l'exception couvre toute la séquence.
    """
    failed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        failed_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        return_value=make_order(status=OrderStatus.FAILED)
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert mock_connector.place_order.call_count == 1
    assert len(failed_events) == 1  # AC4 : TRADE_FAILED émis même quand entry échoue
    assert failed_events[0].event_type == EventType.TRADE_FAILED
    assert failed_events[0].pair == "BTC/USDT"


# ── Test retour None sur tout échec ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_returns_none_on_failure(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """AC4 : retour None ET TRADE_FAILED émis sur tout échec de la séquence atomique."""
    failed_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        failed_events.append(event)

    event_bus.on(EventType.TRADE_FAILED, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=RuntimeError("Erreur réseau inattendue")
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(failed_events) == 1  # AC4 : TRADE_FAILED émis sur exception inattendue
    assert failed_events[0].event_type == EventType.TRADE_FAILED


# ── Test fermeture impossible ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_close_failure_emits_error_critical(
    executor: TradeExecutor, mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """Si close échoue → ERROR_CRITICAL émis (position non protégée)."""
    critical_events: list = []

    async def capture(event):  # type: ignore[no-untyped-def]
        critical_events.append(event)

    event_bus.on(EventType.ERROR_CRITICAL, capture)

    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(status=OrderStatus.FILLED),           # entry OK
            OrderFailedError("SL impossible"),                # SL échoue
            RuntimeError("Fermeture impossible"),             # close échoue aussi
        ]
    )
    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    assert result is None
    assert len(critical_events) == 1
    assert critical_events[0].event_type == EventType.ERROR_CRITICAL
    assert "trade_id" in critical_events[0].message


# ── Test NFR10 — invariant SL ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "side_effects,expected_calls",
    [
        # Scénario 1 : SL exception → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                OrderFailedError("SL fail"),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
        # Scénario 2 : SL statut FAILED → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.FAILED),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
        # Scénario 3 : SL statut CANCELLED → fermeture déclenchée
        (
            [
                make_order(status=OrderStatus.FILLED),
                make_order(order_type=OrderType.STOP_LOSS, status=OrderStatus.CANCELLED),
                make_order(side=OrderSide.SELL),
            ],
            3,
        ),
    ],
)
async def test_nfr10_all_trades_have_sl_or_are_closed(
    mock_connector: MagicMock,
    event_bus: EventBus,
    side_effects: list,
    expected_calls: int,
) -> None:
    """NFR10 : 100% des trades ont SL actif OU position fermée — 0% non protégés."""
    executor = TradeExecutor(connector=mock_connector, event_bus=event_bus)
    mock_connector.place_order = AsyncMock(side_effect=side_effects)

    result = await executor.execute_atomic_trade(**COMMON_PARAMS)

    # Dans tous les scénarios d'échec, position est fermée (None retourné)
    assert result is None
    # L'ordre de fermeture a été tenté
    assert mock_connector.place_order.call_count == expected_calls


# ── Test stop() — graceful shutdown ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_unsubscribes_from_bus(
    mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """Appeler stop() retire les handlers — les signaux suivants ne sont plus traités."""
    executor = TradeExecutor(connector=mock_connector, event_bus=event_bus)

    # Vérifier que les handlers sont bien enregistrés avant stop()
    assert event_bus.has_handlers(EventType.STRATEGY_SIGNAL_LONG)
    assert event_bus.has_handlers(EventType.STRATEGY_SIGNAL_SHORT)

    await executor.stop()

    # Après stop(), les handlers doivent être retirés
    assert not event_bus.has_handlers(EventType.STRATEGY_SIGNAL_LONG)
    assert not event_bus.has_handlers(EventType.STRATEGY_SIGNAL_SHORT)


# ── Tests direction SHORT ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_short_success_uses_sell_entry(
    mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """H2 : direction SHORT → ordre d'entrée SELL et SL côté BUY."""
    executor = TradeExecutor(connector=mock_connector, event_bus=event_bus)
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(side=OrderSide.SELL, status=OrderStatus.FILLED, price=Decimal("50000")),
            make_order(side=OrderSide.BUY, order_type=OrderType.STOP_LOSS, status=OrderStatus.PENDING),
        ]
    )
    result = await executor.execute_atomic_trade(
        pair="BTC/USDT",
        direction=TradeDirection.SHORT,
        quantity=Decimal("0.01"),
        sl_price=Decimal("51000"),
        capital_before=Decimal("1000"),
    )

    assert result is not None
    assert result.status == TradeStatus.OPEN
    assert result.direction == TradeDirection.SHORT
    # Vérifier que l'entrée est un SELL (direction SHORT)
    entry_call = mock_connector.place_order.call_args_list[0]
    assert entry_call.kwargs["side"] == OrderSide.SELL
    # Vérifier que le SL est un BUY (close_side pour SHORT)
    sl_call = mock_connector.place_order.call_args_list[1]
    assert sl_call.kwargs["side"] == OrderSide.BUY


@pytest.mark.asyncio
async def test_atomic_trade_short_sl_failure_closes_with_buy(
    mock_connector: MagicMock, event_bus: EventBus
) -> None:
    """H2 : direction SHORT + SL exception → fermeture via ordre BUY (close_side inverse)."""
    executor = TradeExecutor(connector=mock_connector, event_bus=event_bus)
    mock_connector.place_order = AsyncMock(
        side_effect=[
            make_order(side=OrderSide.SELL, status=OrderStatus.FILLED),  # entry SELL
            OrderFailedError("SL impossible"),                             # SL échoue
            make_order(side=OrderSide.BUY, order_type=OrderType.MARKET),  # close BUY
        ]
    )
    result = await executor.execute_atomic_trade(
        pair="BTC/USDT",
        direction=TradeDirection.SHORT,
        quantity=Decimal("0.01"),
        sl_price=Decimal("51000"),
        capital_before=Decimal("1000"),
    )

    assert result is None
    assert mock_connector.place_order.call_count == 3
    # Vérifier que la fermeture utilise BUY (inverse du SELL d'entrée SHORT)
    close_call = mock_connector.place_order.call_args_list[2]
    assert close_call.kwargs["side"] == OrderSide.BUY


# ── Tests validation paramètres (M2) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_trade_invalid_quantity_raises_value_error(
    executor: TradeExecutor,
) -> None:
    """M2 : quantity <= 0 lève ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="quantity doit être > 0"):
        await executor.execute_atomic_trade(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0"),
            sl_price=Decimal("49000"),
            capital_before=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_atomic_trade_invalid_sl_price_raises_value_error(
    executor: TradeExecutor,
) -> None:
    """M2 : sl_price <= 0 lève ValueError avant tout appel réseau."""
    with pytest.raises(ValueError, match="sl_price doit être > 0"):
        await executor.execute_atomic_trade(
            pair="BTC/USDT",
            direction=TradeDirection.LONG,
            quantity=Decimal("0.01"),
            sl_price=Decimal("0"),
            capital_before=Decimal("1000"),
        )
