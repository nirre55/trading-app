"""Connecteur CCXT Pro avec WebSocket, gestion de connexion et auto-reconnexion."""

import asyncio
from decimal import Decimal
from typing import Any

import ccxt.pro
from loguru import logger

from src.core.event_bus import EventBus
from src.core.exceptions import (
    ExchangeConnectionError,
    ExchangeError,
    InsufficientBalanceError,
)
from src.exchange.base import BaseExchangeConnector
from src.exchange.rate_limiter import RateLimitConfig, RateLimiter
from src.models.config import ExchangeConfig
from src.models.events import CandleEvent, ErrorEvent, EventType, ExchangeEvent
from src.models.exchange import Balance, MarketRules, OrderInfo, OrderSide, OrderType

__all__ = ["CcxtConnector"]

MAX_RECONNECT_ATTEMPTS = 5
INITIAL_RECONNECT_DELAY = 2.0
MAX_RECONNECT_DELAY = 30.0


class CcxtConnector(BaseExchangeConnector):
    """Connecteur CCXT Pro avec WebSocket et gestion de connexion."""

    def __init__(
        self,
        exchange_config: ExchangeConfig,
        event_bus: EventBus,
        pair: str,
        timeframe: str,
    ) -> None:
        super().__init__(exchange_config, event_bus, pair, timeframe)
        self._exchange: Any = None
        self._exchange_name: str = exchange_config.name
        self._reconnect_attempts: int = 0
        self._is_connected: bool = False
        self._rate_limiter: RateLimiter = RateLimiter(RateLimitConfig())

    async def connect(self) -> None:
        """Connecte a l'exchange via CCXT Pro, charge les marches et les regles."""
        if self._exchange is not None:
            logger.warning("Connexion deja active pour {}, deconnexion prealable", self._exchange_name)
            await self.disconnect()

        try:
            exchange_class = getattr(ccxt.pro, self._exchange_name)
            self._exchange = exchange_class(
                {
                    "apiKey": self._exchange_config.api_key.get_secret_value(),
                    "secret": self._exchange_config.api_secret.get_secret_value(),
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "future",
                    },
                }
            )

            if self._exchange_config.testnet:
                self._exchange.set_sandbox_mode(True)
                logger.info("Mode testnet active pour {}", self._exchange_name)

            logger.info("Connexion a {} en cours...", self._exchange_name)
            await self._exchange.load_markets()
            logger.info("Marches charges pour {}", self._exchange_name)

            self._market_rules = await self.fetch_market_rules(self._pair)
            logger.info(
                "Regles de marche chargees pour {} : {}",
                self._pair,
                self._market_rules,
            )

            self._is_connected = True
            self._reconnect_attempts = 0

            logger.info(
                "Rate limiter initialise: {} req/s, burst {}",
                self._rate_limiter._config.max_requests_per_second,
                self._rate_limiter._config.burst_size,
            )

            await self._event_bus.emit(
                EventType.EXCHANGE_CONNECTED,
                ExchangeEvent(
                    event_type=EventType.EXCHANGE_CONNECTED,
                    exchange_name=self._exchange_name,
                    details=f"Connecte a {self._exchange_name} (pair={self._pair}, timeframe={self._timeframe})",
                ),
            )
            logger.info("Connecte a {} avec succes", self._exchange_name)

        except ExchangeError:
            raise
        except (ccxt.NetworkError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable) as exc:
            logger.error("Echec de connexion a {} : {}", self._exchange_name, exc)
            raise ExchangeConnectionError(
                f"Echec de connexion a {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc
        except ccxt.BaseError as exc:
            logger.error("Erreur exchange {} : {}", self._exchange_name, exc)
            raise ExchangeError(
                f"Erreur exchange {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc
        except Exception as exc:
            logger.error("Echec de connexion a {} : {}", self._exchange_name, exc)
            raise ExchangeConnectionError(
                f"Echec de connexion a {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc

    async def disconnect(self) -> None:
        """Deconnecte l'exchange et ferme les WebSockets."""
        if self._exchange is not None:
            self._is_connected = False
            logger.info("Deconnexion de {} en cours...", self._exchange_name)
            await self._exchange.close()
            self._exchange = None
            logger.info("Deconnecte de {}", self._exchange_name)

            await self._event_bus.emit(
                EventType.EXCHANGE_DISCONNECTED,
                ExchangeEvent(
                    event_type=EventType.EXCHANGE_DISCONNECTED,
                    exchange_name=self._exchange_name,
                    details=f"Deconnecte de {self._exchange_name}",
                ),
            )
        else:
            logger.debug("disconnect() appele mais aucune connexion active pour {}", self._exchange_name)

    async def watch_candles(self) -> None:
        """Surveille les bougies via WebSocket et emet les evenements candle.closed."""
        prev_candle_ts: int | None = None
        prev_candle_data: list | None = None

        logger.info(
            "Demarrage de la surveillance des bougies {} {}",
            self._pair,
            self._timeframe,
        )

        while True:
            try:
                ohlcvs = await self._exchange.watch_ohlcv(self._pair, self._timeframe)
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as exc:
                logger.warning(
                    "Deconnexion detectee sur {} : {}",
                    self._exchange_name,
                    exc,
                )
                self._is_connected = False
                await self._event_bus.emit(
                    EventType.EXCHANGE_DISCONNECTED,
                    ExchangeEvent(
                        event_type=EventType.EXCHANGE_DISCONNECTED,
                        exchange_name=self._exchange_name,
                        details=f"Deconnexion detectee sur {self._exchange_name} : {exc}",
                    ),
                )
                await self._reconnect()
                continue
            except ccxt.AuthenticationError as exc:
                logger.error(
                    "Erreur d'authentification sur {} : {}",
                    self._exchange_name,
                    exc,
                )
                await self._event_bus.emit(
                    EventType.ERROR_CRITICAL,
                    ErrorEvent(
                        event_type=EventType.ERROR_CRITICAL,
                        error_type="AuthenticationError",
                        message=f"Erreur d'authentification sur {self._exchange_name} : {exc}",
                    ),
                )
                raise ExchangeConnectionError(
                    f"Erreur d'authentification sur {self._exchange_name} : {exc}",
                    context={"exchange": self._exchange_name, "error": str(exc)},
                ) from exc

            if not ohlcvs:
                continue

            current = ohlcvs[-1]
            current_ts = current[0]

            if prev_candle_ts is not None and current_ts != prev_candle_ts:
                closed_data = None
                for c in ohlcvs:
                    if c[0] == prev_candle_ts:
                        closed_data = c
                        break
                if closed_data is None:
                    closed_data = prev_candle_data
                if closed_data is not None:
                    await self._emit_candle_closed(closed_data)

            prev_candle_ts = current_ts
            prev_candle_data = list(current)

    async def _reconnect(self) -> None:
        """Tente la reconnexion avec backoff exponentiel."""
        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            delay = min(INITIAL_RECONNECT_DELAY * (2 ** attempt), MAX_RECONNECT_DELAY)
            self._reconnect_attempts = attempt + 1

            logger.info(
                "Tentative de reconnexion {}/{} pour {} dans {:.1f}s",
                self._reconnect_attempts,
                MAX_RECONNECT_ATTEMPTS,
                self._exchange_name,
                delay,
            )

            await asyncio.sleep(delay)

            try:
                await self._exchange.load_markets()
                self._is_connected = True
                self._reconnect_attempts = 0

                logger.info("Reconnexion reussie a {}", self._exchange_name)

                await self._event_bus.emit(
                    EventType.EXCHANGE_RECONNECTED,
                    ExchangeEvent(
                        event_type=EventType.EXCHANGE_RECONNECTED,
                        exchange_name=self._exchange_name,
                        details=f"Reconnecte a {self._exchange_name} apres {attempt + 1} tentative(s)",
                    ),
                )

                await self._verify_positions_after_reconnect()
                return

            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as exc:
                logger.warning(
                    "Echec tentative {}/{} pour {} : {}",
                    self._reconnect_attempts,
                    MAX_RECONNECT_ATTEMPTS,
                    self._exchange_name,
                    exc,
                )
            except ccxt.AuthenticationError as exc:
                logger.error(
                    "Erreur d'authentification lors de la reconnexion a {} : {}",
                    self._exchange_name,
                    exc,
                )
                await self._event_bus.emit(
                    EventType.ERROR_CRITICAL,
                    ErrorEvent(
                        event_type=EventType.ERROR_CRITICAL,
                        error_type="AuthenticationError",
                        message=f"Erreur d'authentification sur {self._exchange_name} : {exc}",
                    ),
                )
                raise ExchangeConnectionError(
                    f"Erreur d'authentification sur {self._exchange_name} : {exc}",
                    context={"exchange": self._exchange_name, "error": str(exc)},
                ) from exc
            except ccxt.BaseError as exc:
                logger.warning(
                    "Echec tentative {}/{} pour {} : {}",
                    self._reconnect_attempts,
                    MAX_RECONNECT_ATTEMPTS,
                    self._exchange_name,
                    exc,
                )

        logger.error(
            "Echec de reconnexion a {} apres {} tentatives",
            self._exchange_name,
            MAX_RECONNECT_ATTEMPTS,
        )
        await self._event_bus.emit(
            EventType.ERROR_CRITICAL,
            ErrorEvent(
                event_type=EventType.ERROR_CRITICAL,
                error_type="ReconnectionFailed",
                message=f"Echec de reconnexion a {self._exchange_name} apres {MAX_RECONNECT_ATTEMPTS} tentatives",
            ),
        )
        raise ExchangeConnectionError(
            f"Echec de reconnexion a {self._exchange_name} apres {MAX_RECONNECT_ATTEMPTS} tentatives",
            context={"exchange": self._exchange_name, "attempts": MAX_RECONNECT_ATTEMPTS},
        )

    async def fetch_market_rules(self, pair: str) -> MarketRules:
        """Recupere les regles de marche pour une paire depuis l'exchange."""

        async def _do_fetch() -> MarketRules:
            if pair not in self._exchange.markets:
                logger.error("Paire {} non trouvee sur {}", pair, self._exchange_name)
                raise ExchangeError(
                    f"Paire {pair} non trouvee sur {self._exchange_name}",
                    context={"pair": pair, "exchange": self._exchange_name},
                )

            market = self._exchange.markets[pair]

            step_size = Decimal(str(market["precision"]["amount"]))
            tick_size = Decimal(str(market["precision"]["price"]))
            min_notional = (
                Decimal(str(market["limits"]["cost"]["min"]))
                if market["limits"]["cost"]["min"] is not None
                else Decimal("0")
            )
            max_leverage = (
                int(market["limits"]["leverage"]["max"])
                if market["limits"]["leverage"]["max"] is not None
                else 1
            )

            rules = MarketRules(
                step_size=step_size,
                tick_size=tick_size,
                min_notional=min_notional,
                max_leverage=max_leverage,
            )
            logger.debug("Regles de marche pour {} : {}", pair, rules)
            return rules

        return await self._rate_limiter.execute(_do_fetch)

    async def place_order(
        self,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderInfo:
        """Stub — implemente dans Story 4.1."""
        # TODO Story 4.1: utiliser OrderPriority.CRITICAL pour SL, HIGH pour TP
        raise NotImplementedError("Implemente dans Story 4.1")

    async def cancel_order(self, order_id: str) -> None:
        """Stub — implemente dans Story 4.1."""
        # TODO Story 4.1: utiliser OrderPriority.CRITICAL pour SL, HIGH pour TP
        raise NotImplementedError("Implemente dans Story 4.1")

    async def fetch_balance(self) -> Balance:
        """Recupere la balance du compte depuis l'exchange."""

        async def _do_fetch() -> Balance:
            result = await self._exchange.fetch_balance()
            usdt = result["USDT"]
            balance = Balance(
                total=Decimal(str(usdt["total"])),
                free=Decimal(str(usdt["free"])),
                used=Decimal(str(usdt["used"])),
                currency="USDT",
            )
            logger.info(
                "Balance recuperee: {} USDT disponible sur {} USDT total",
                balance.free,
                balance.total,
            )
            return balance

        try:
            return await self._rate_limiter.execute(_do_fetch)
        except ccxt.NetworkError as exc:
            logger.error("Erreur reseau lors de fetch_balance sur {} : {}", self._exchange_name, exc)
            raise ExchangeConnectionError(
                f"Erreur reseau lors de fetch_balance sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc
        except ccxt.AuthenticationError as exc:
            logger.error("Erreur d'authentification lors de fetch_balance sur {} : {}", self._exchange_name, exc)
            raise ExchangeError(
                f"Erreur d'authentification lors de fetch_balance sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc
        except ccxt.BaseError as exc:
            logger.error("Erreur exchange lors de fetch_balance sur {} : {}", self._exchange_name, exc)
            raise ExchangeError(
                f"Erreur exchange lors de fetch_balance sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc

    async def check_balance(self, min_required: Decimal) -> Balance:
        """Verifie que la balance libre est suffisante pour trader."""
        balance = await self.fetch_balance()

        if balance.free < min_required:
            logger.error(
                "Balance insuffisante: {} USDT disponible, {} USDT requis",
                balance.free,
                min_required,
            )
            await self._event_bus.emit(
                EventType.ERROR_CRITICAL,
                ErrorEvent(
                    event_type=EventType.ERROR_CRITICAL,
                    error_type="InsufficientBalance",
                    message=f"Balance insuffisante: {balance.free} USDT disponible, {min_required} USDT requis",
                ),
            )
            raise InsufficientBalanceError(
                f"Balance insuffisante: {balance.free} USDT disponible, {min_required} USDT requis",
                context={
                    "free": str(balance.free),
                    "required": str(min_required),
                    "currency": balance.currency,
                },
            )

        logger.info(
            "Balance suffisante: {} USDT >= {} USDT",
            balance.free,
            min_required,
        )
        return balance

    async def fetch_positions(self) -> list[dict[str, Any]]:
        """Recupere les positions ouvertes sur l'exchange."""

        async def _do_fetch() -> list[dict[str, Any]]:
            positions = await self._exchange.fetch_positions([self._pair])
            open_positions = [p for p in positions if p.get("contracts", 0) > 0]
            logger.info(
                "{} position(s) ouverte(s) trouvee(s) sur {} pour {}",
                len(open_positions),
                self._exchange_name,
                self._pair,
            )
            return open_positions

        try:
            return await self._rate_limiter.execute(_do_fetch)
        except ccxt.NetworkError as exc:
            logger.error("Erreur reseau lors de fetch_positions sur {} : {}", self._exchange_name, exc)
            raise ExchangeConnectionError(
                f"Erreur reseau lors de fetch_positions sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc
        except ccxt.BaseError as exc:
            logger.error("Erreur exchange lors de fetch_positions sur {} : {}", self._exchange_name, exc)
            raise ExchangeError(
                f"Erreur exchange lors de fetch_positions sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc

    async def _verify_positions_after_reconnect(self) -> None:
        """Verifie que les positions ouvertes ont toujours un SL actif apres reconnexion."""
        try:
            positions = await self.fetch_positions()
        except (ExchangeConnectionError, ExchangeError) as exc:
            logger.error("Impossible de verifier les positions apres reconnexion : {}", exc)
            await self._event_bus.emit(
                EventType.ERROR_CRITICAL,
                ErrorEvent(
                    event_type=EventType.ERROR_CRITICAL,
                    error_type="PositionVerificationFailed",
                    message=f"Impossible de verifier les positions apres reconnexion sur {self._exchange_name} : {exc}",
                ),
            )
            raise

        if not positions:
            logger.info("Aucune position ouverte, verification OK")
            return

        try:
            async def _do_fetch_orders() -> list:
                return await self._exchange.fetch_open_orders(self._pair)

            open_orders = await self._rate_limiter.execute(_do_fetch_orders)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.BaseError) as exc:
            logger.error("Impossible de recuperer les ordres ouverts : {}", exc)
            await self._event_bus.emit(
                EventType.ERROR_CRITICAL,
                ErrorEvent(
                    event_type=EventType.ERROR_CRITICAL,
                    error_type="OrderVerificationFailed",
                    message=f"Impossible de verifier les ordres SL sur {self._exchange_name} : {exc}",
                ),
            )
            raise ExchangeConnectionError(
                f"Impossible de verifier les ordres SL sur {self._exchange_name} : {exc}",
                context={"exchange": self._exchange_name, "error": str(exc)},
            ) from exc

        sl_orders = [
            o for o in open_orders
            if o.get("type", "").lower() in ("stop_market", "stop", "stop_loss")
            or o.get("stopPrice") is not None
        ]

        unprotected: list[dict[str, Any]] = []

        for position in positions:
            symbol = position.get("symbol", self._pair)
            pos_side = position.get("side", "").lower()
            expected_sl_side = "sell" if pos_side == "long" else "buy"
            has_sl = any(
                o.get("symbol") == symbol and o.get("side", "").lower() == expected_sl_side
                for o in sl_orders
            )
            if not has_sl:
                unprotected.append(position)

        positions_with_sl = len(positions) - len(unprotected)

        logger.info(
            "Verification post-reconnexion : {} positions ouvertes, {} avec SL actif, {} sans SL",
            len(positions),
            positions_with_sl,
            len(unprotected),
        )

        if unprotected:
            for p in unprotected:
                logger.error(
                    "Position sans SL detectee : {} {} contracts={}",
                    p.get("symbol"),
                    p.get("side"),
                    p.get("contracts"),
                )
            await self._event_bus.emit(
                EventType.ERROR_CRITICAL,
                ErrorEvent(
                    event_type=EventType.ERROR_CRITICAL,
                    error_type="MissingStopLoss",
                    message=f"{len(unprotected)} position(s) sans SL detectee(s) sur {self._exchange_name}",
                ),
            )

    async def _emit_candle_closed(self, candle_data: list) -> None:
        """Emet un evenement candle.closed sur le bus."""
        candle_event = CandleEvent(
            event_type=EventType.CANDLE_CLOSED,
            pair=self._pair,
            timeframe=self._timeframe,
            open=Decimal(str(candle_data[1])),
            high=Decimal(str(candle_data[2])),
            low=Decimal(str(candle_data[3])),
            close=Decimal(str(candle_data[4])),
            volume=Decimal(str(candle_data[5])),
        )
        logger.debug(
            "Bougie fermee {} {} : close={}",
            self._pair,
            self._timeframe,
            candle_event.close,
        )
        await self._event_bus.emit(EventType.CANDLE_CLOSED, candle_event)
