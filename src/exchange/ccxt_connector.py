"""Connecteur CCXT Pro avec WebSocket et gestion de connexion."""

from decimal import Decimal
from typing import Any

import ccxt.pro
from loguru import logger

from src.core.event_bus import EventBus
from src.core.exceptions import ExchangeConnectionError, ExchangeError
from src.exchange.base import BaseExchangeConnector
from src.models.config import ExchangeConfig
from src.models.events import CandleEvent, EventType, ExchangeEvent
from src.models.exchange import Balance, MarketRules, OrderInfo, OrderSide, OrderType

__all__ = ["CcxtConnector"]


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
            ohlcvs = await self._exchange.watch_ohlcv(self._pair, self._timeframe)
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

    async def fetch_market_rules(self, pair: str) -> MarketRules:
        """Recupere les regles de marche pour une paire depuis l'exchange."""
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

    async def place_order(
        self,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderInfo:
        """Stub — implemente dans Story 4.1."""
        raise NotImplementedError("Implemente dans Story 4.1")

    async def cancel_order(self, order_id: str) -> None:
        """Stub — implemente dans Story 4.1."""
        raise NotImplementedError("Implemente dans Story 4.1")

    async def fetch_balance(self) -> Balance:
        """Stub — implemente dans Story 2.3."""
        raise NotImplementedError("Implemente dans Story 2.3")

    async def fetch_positions(self) -> list[dict[str, Any]]:
        """Stub — implemente dans Story 2.2."""
        raise NotImplementedError("Implemente dans Story 2.2")

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
