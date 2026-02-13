"""Rate limiter adaptatif avec priorite pour les requetes API exchange."""

import asyncio
import heapq
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import TypeVar

import ccxt
from loguru import logger
from pydantic import BaseModel

__all__ = ["RateLimiter", "OrderPriority", "RateLimitConfig"]

T = TypeVar("T")


class OrderPriority(IntEnum):
    """Priorite des ordres pour le rate limiter. Valeur basse = priorite haute."""

    CRITICAL = 0  # SL — jamais abandonne
    HIGH = 1  # TP
    NORMAL = 2  # Autres requetes


class RateLimitConfig(BaseModel):
    """Configuration du rate limiter."""

    max_requests_per_second: int = 10
    burst_size: int = 5
    retry_delay: float = 1.0
    max_retry_delay: float = 30.0
    max_retries: int = 10


class RateLimiter:
    """Rate limiter avec algorithme token bucket et file d'attente par priorite."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._tokens: float = float(self._config.burst_size)
        self._max_tokens: float = float(self._config.burst_size)
        self._refill_rate: float = float(self._config.max_requests_per_second)
        self._last_refill: float = 0.0
        self._initialized: bool = False
        self._lock = asyncio.Lock()
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._sequence: int = 0
        self._retry_after_delay: float | None = None

    def _refill(self) -> None:
        """Recharge les tokens en fonction du temps ecoule."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        if not self._initialized:
            self._last_refill = now
            self._initialized = True
            return
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._refill_rate)

    def _dispatch_tokens(self) -> None:
        """Distribue les tokens disponibles aux waiters par priorite."""
        while self._tokens >= 1 and self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                self._tokens -= 1
                future.set_result(None)

    async def acquire(self, priority: OrderPriority = OrderPriority.NORMAL) -> None:
        """Acquiert un slot du rate limiter avec gestion de priorite."""
        # Fast path: token disponible et pas de waiters
        async with self._lock:
            self._refill()
            if self._tokens >= 1 and not self._waiters:
                self._tokens -= 1
                logger.debug(
                    "Token acquis (priorite={}), tokens restants: {:.1f}",
                    priority.name,
                    self._tokens,
                )
                return

        # Slow path: enregistrer comme waiter et attendre
        async with self._lock:
            future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            seq = self._sequence
            self._sequence += 1
            heapq.heappush(self._waiters, (priority.value, seq, future))
            # Peut-etre qu'un token est disponible maintenant
            self._refill()
            self._dispatch_tokens()

        retry_count = 0
        while not future.done():
            # Utiliser le delai Retry-After de l'exchange si disponible
            if self._retry_after_delay is not None:
                delay = self._retry_after_delay
                self._retry_after_delay = None
            else:
                delay = self._config.retry_delay * (2 ** min(retry_count, 5))
                delay = min(delay, self._config.max_retry_delay)

            logger.debug(
                "En attente de token (priorite={}, delai={:.1f}s)",
                priority.name,
                delay,
            )
            await asyncio.sleep(delay)

            if future.done():
                break

            async with self._lock:
                self._refill()
                self._dispatch_tokens()

            retry_count += 1

            if not future.done():
                if priority != OrderPriority.CRITICAL and retry_count >= self._config.max_retries:
                    # Retirer de la queue
                    async with self._lock:
                        self._waiters = [w for w in self._waiters if w[2] is not future]
                        heapq.heapify(self._waiters)
                    logger.warning(
                        "Rate limit epuise apres {} tentatives (priorite={})",
                        retry_count,
                        priority.name,
                    )
                    from src.core.exceptions import RateLimitError

                    raise RateLimitError(
                        f"Rate limit epuise apres {retry_count} tentatives",
                        context={"priority": priority.name, "retries": retry_count},
                    )

                logger.info(
                    "Retry {}/{} pour acquisition de token (priorite={})",
                    retry_count,
                    "inf" if priority == OrderPriority.CRITICAL else self._config.max_retries,
                    priority.name,
                )

        logger.debug(
            "Token acquis apres attente (priorite={}), tokens restants: {:.1f}",
            priority.name,
            self._tokens,
        )

    async def execute(
        self,
        coroutine_func: Callable[[], Awaitable[T]],
        priority: OrderPriority = OrderPriority.NORMAL,
    ) -> T:
        """Execute une coroutine apres acquisition d'un slot rate limiter."""
        retry_count = 0

        while True:
            await self.acquire(priority)
            try:
                result = await coroutine_func()
                return result
            except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as exc:
                retry_count += 1
                logger.warning(
                    "Rate limit exchange detecte (tentative {}/{}): {}",
                    retry_count,
                    self._config.max_retries,
                    exc,
                )
                self.handle_rate_limit_error(exc)
                if retry_count >= self._config.max_retries:
                    raise
                continue

    def handle_rate_limit_error(self, error: Exception) -> None:
        """Gere une erreur de rate limit exchange et ajuste le delai d'attente."""
        retry_after = None
        headers = getattr(error, "headers", None)
        if headers:
            retry_after = headers.get("Retry-After")

        if retry_after:
            try:
                self._retry_after_delay = float(retry_after)
            except (ValueError, TypeError):
                self._retry_after_delay = None
            logger.warning("Rate limit exchange avec Retry-After: {}s", retry_after)
        else:
            logger.warning("Rate limit exchange detecte: {}", error)
