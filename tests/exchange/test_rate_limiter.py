"""Tests du rate limiter avec priorite."""

import asyncio
from unittest.mock import AsyncMock, patch

import ccxt
import pytest

from src.core.exceptions import RateLimitError
from src.exchange.rate_limiter import OrderPriority, RateLimitConfig, RateLimiter


def _add_token(limiter: RateLimiter) -> None:
    """Ajoute un token au rate limiter en contournant _refill()."""
    limiter._max_tokens = max(limiter._max_tokens, limiter._tokens + 1)
    limiter._tokens += 1


class TestRateLimiterPriority:
    """Tests de priorite des ordres."""

    @pytest.mark.asyncio
    async def test_acquire_critical_priority_served_first(self) -> None:
        """Un ordre CRITICAL est servi avant un NORMAL en file d'attente."""
        config = RateLimitConfig(max_requests_per_second=1, burst_size=0, retry_delay=0.01)
        limiter = RateLimiter(config)

        # Enregistrer manuellement les waiters dans l'ordre : NORMAL puis CRITICAL
        future_normal: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        future_critical: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        import heapq
        heapq.heappush(limiter._waiters, (OrderPriority.NORMAL.value, 0, future_normal))
        heapq.heappush(limiter._waiters, (OrderPriority.CRITICAL.value, 1, future_critical))

        # Ajouter un seul token et dispatcher
        _add_token(limiter)
        limiter._dispatch_tokens()

        # CRITICAL doit etre servi en premier
        assert future_critical.done()
        assert not future_normal.done()

        # Ajouter un autre token pour NORMAL
        _add_token(limiter)
        limiter._dispatch_tokens()
        assert future_normal.done()

    @pytest.mark.asyncio
    async def test_acquire_high_priority_before_normal(self) -> None:
        """Un ordre HIGH est servi avant NORMAL."""
        config = RateLimitConfig(max_requests_per_second=1, burst_size=0, retry_delay=0.01)
        limiter = RateLimiter(config)

        future_normal: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        future_high: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        import heapq
        heapq.heappush(limiter._waiters, (OrderPriority.NORMAL.value, 0, future_normal))
        heapq.heappush(limiter._waiters, (OrderPriority.HIGH.value, 1, future_high))

        _add_token(limiter)
        limiter._dispatch_tokens()

        assert future_high.done()
        assert not future_normal.done()

    @pytest.mark.asyncio
    async def test_acquire_critical_never_abandoned(self) -> None:
        """Un ordre CRITICAL reessaie indefiniment (au moins 3 retries)."""
        config = RateLimitConfig(
            max_requests_per_second=1,
            burst_size=1,
            retry_delay=0.01,
            max_retries=3,
        )
        limiter = RateLimiter(config)

        # Consommer le token initial
        await limiter.acquire(OrderPriority.NORMAL)

        sleep_count = 0
        original_sleep = asyncio.sleep

        async def mock_sleep(delay: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            await original_sleep(0)
            if sleep_count >= 5:
                _add_token(limiter)

        with patch("src.exchange.rate_limiter.asyncio.sleep", side_effect=mock_sleep):
            await asyncio.wait_for(
                limiter.acquire(OrderPriority.CRITICAL),
                timeout=5.0,
            )

        # CRITICAL ne doit jamais etre abandonne — il a reessaye au moins 3 fois
        assert sleep_count >= 3

    @pytest.mark.asyncio
    async def test_priority_order_sl_tp_other(self) -> None:
        """Avec 3 ordres simultanes, ordre d'execution: CRITICAL -> HIGH -> NORMAL."""
        config = RateLimitConfig(max_requests_per_second=1, burst_size=1, retry_delay=0.01)
        limiter = RateLimiter(config)

        execution_order: list[str] = []

        # Enregistrer 3 waiters avec priorites differentes
        future_normal: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        future_high: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        future_critical: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        import heapq
        # Enregistrer dans l'ordre inverse de priorite (NORMAL en premier, CRITICAL en dernier)
        heapq.heappush(limiter._waiters, (OrderPriority.NORMAL.value, 0, future_normal))
        heapq.heappush(limiter._waiters, (OrderPriority.HIGH.value, 1, future_high))
        heapq.heappush(limiter._waiters, (OrderPriority.CRITICAL.value, 2, future_critical))

        # Distribuer les tokens un par un
        _add_token(limiter)
        limiter._dispatch_tokens()
        if future_critical.done():
            execution_order.append("critical")
        if future_high.done():
            execution_order.append("high")
        if future_normal.done():
            execution_order.append("normal")

        _add_token(limiter)
        limiter._dispatch_tokens()
        if future_high.done() and "high" not in execution_order:
            execution_order.append("high")
        if future_normal.done() and "normal" not in execution_order:
            execution_order.append("normal")

        _add_token(limiter)
        limiter._dispatch_tokens()
        if future_normal.done() and "normal" not in execution_order:
            execution_order.append("normal")

        assert execution_order == ["critical", "high", "normal"]


class TestRateLimiterTokenBucket:
    """Tests de l'algorithme token bucket."""

    @pytest.mark.asyncio
    async def test_token_bucket_allows_burst(self) -> None:
        """Les premieres burst_size requetes passent immediatement."""
        config = RateLimitConfig(max_requests_per_second=1, burst_size=5, retry_delay=0.01)
        limiter = RateLimiter(config)

        with patch("src.exchange.rate_limiter.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            for _ in range(5):
                await limiter.acquire(OrderPriority.NORMAL)

            # Aucun sleep ne devrait avoir ete appele pour les 5 premiers
            mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_token_bucket_refills_over_time(self) -> None:
        """Apres epuisement, les tokens se rechargent au rythme refill_rate."""
        config = RateLimitConfig(max_requests_per_second=10, burst_size=1, retry_delay=0.01)
        limiter = RateLimiter(config)

        # Consommer le token
        await limiter.acquire(OrderPriority.NORMAL)
        assert limiter._tokens < 1

        original_sleep = asyncio.sleep

        async def mock_sleep(delay: float) -> None:
            _add_token(limiter)
            await original_sleep(0)

        with patch("src.exchange.rate_limiter.asyncio.sleep", side_effect=mock_sleep):
            await limiter.acquire(OrderPriority.NORMAL)

    @pytest.mark.asyncio
    async def test_token_bucket_blocks_when_empty(self) -> None:
        """Quand 0 tokens, acquire() appelle asyncio.sleep()."""
        config = RateLimitConfig(max_requests_per_second=1, burst_size=1, retry_delay=0.01)
        limiter = RateLimiter(config)

        # Consommer le token
        await limiter.acquire(OrderPriority.NORMAL)

        sleep_called = False
        original_sleep = asyncio.sleep

        async def mock_sleep(delay: float) -> None:
            nonlocal sleep_called
            sleep_called = True
            _add_token(limiter)
            await original_sleep(0)

        with patch("src.exchange.rate_limiter.asyncio.sleep", side_effect=mock_sleep):
            await limiter.acquire(OrderPriority.NORMAL)

        assert sleep_called is True


class TestRateLimiterExecute:
    """Tests d'execution avec rate limit."""

    @pytest.mark.asyncio
    async def test_execute_wraps_coroutine_with_rate_limit(self) -> None:
        """execute() appelle acquire() puis la coroutine."""
        config = RateLimitConfig(burst_size=5)
        limiter = RateLimiter(config)

        mock_coro = AsyncMock(return_value="result")

        result = await limiter.execute(mock_coro)

        assert result == "result"
        mock_coro.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_retries_on_rate_limit_error(self) -> None:
        """execute() reessaie si la coroutine leve ccxt.RateLimitExceeded."""
        config = RateLimitConfig(burst_size=5)
        limiter = RateLimiter(config)

        call_count = 0

        async def failing_then_success() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ccxt.RateLimitExceeded("too many requests")
            return "success"

        result = await limiter.execute(failing_then_success)

        assert result == "success"
        assert call_count == 2


class TestRateLimiterHandleRateLimitError:
    """Tests de handle_rate_limit_error."""

    def test_handle_rate_limit_error_sets_retry_after_delay(self) -> None:
        """Retry-After header est stocke dans _retry_after_delay."""
        from unittest.mock import MagicMock

        limiter = RateLimiter(RateLimitConfig())

        error = MagicMock(spec=ccxt.RateLimitExceeded)
        error.headers = {"Retry-After": "5"}

        limiter.handle_rate_limit_error(error)

        assert limiter._retry_after_delay == 5.0

    def test_handle_rate_limit_error_no_headers(self) -> None:
        """Sans headers, _retry_after_delay reste None."""
        limiter = RateLimiter(RateLimitConfig())

        error = ccxt.RateLimitExceeded("too many requests")

        limiter.handle_rate_limit_error(error)

        assert limiter._retry_after_delay is None

    def test_handle_rate_limit_error_invalid_retry_after(self) -> None:
        """Retry-After invalide ne cause pas d'erreur."""
        from unittest.mock import MagicMock

        limiter = RateLimiter(RateLimitConfig())

        error = MagicMock(spec=ccxt.RateLimitExceeded)
        error.headers = {"Retry-After": "invalid"}

        limiter.handle_rate_limit_error(error)

        assert limiter._retry_after_delay is None
