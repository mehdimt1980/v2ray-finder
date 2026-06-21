"""Async HTTP fetching module with connection pooling and retry logic."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from .exceptions import (
    ErrorType,
    GitHubAPIError,
    NetworkError,
    RateLimitError,
)
from .exceptions import TimeoutError as V2RayTimeoutError
from .exceptions import (
    V2RayFinderError,
)
from .result import Err, Ok, Result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: build structured error dicts
# ---------------------------------------------------------------------------


def _structured(exc: V2RayFinderError) -> dict:
    """Return the to_dict() payload of a V2RayFinderError."""
    return exc.to_dict()


def _timeout_error(url: str) -> Tuple[str, dict]:
    exc = V2RayTimeoutError(f"Request timed out: {url}", url=url)
    return exc.message, _structured(exc)


def _network_error(url: str, detail: str) -> Tuple[str, dict]:
    exc = NetworkError(detail, url=url)
    return exc.message, _structured(exc)


def _rate_limit_error(url: str, status: int) -> Tuple[str, dict]:
    exc = RateLimitError(
        message=f"Rate limit (HTTP {status}): {url}",
        remaining=0,
    )
    return exc.message, _structured(exc)


def _http_error(url: str, status: int) -> Tuple[str, dict]:
    exc = GitHubAPIError(f"HTTP {status}: {url}", status_code=status)
    return exc.message, _structured(exc)


def _unknown_error(url: str, detail: str) -> Tuple[str, dict]:
    from .exceptions import ErrorType, V2RayFinderError

    exc = V2RayFinderError(detail, error_type=ErrorType.UNKNOWN_ERROR)
    return exc.message, _structured(exc)


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of an async fetch operation.

    Attributes
    ----------
    url           : The URL that was fetched.
    content       : Response body text on success, else None.
    status_code   : HTTP status code if a response was received.
    success       : True only when HTTP 200 and content is available.
    error         : Human-readable error string (preserved for back-compat).
    elapsed_ms    : Wall-clock time from request start to completion.
    structured_error : V1-D2 — machine-readable error payload produced from
                    the V2RayFinderError hierarchy.  Always present when
                    ``success`` is False, None otherwise.  Shape::

                        {
                          "error_type": str,   # ErrorType.value
                          "message":    str,
                          "details":    dict,
                        }
    """

    url: str
    content: Optional[str]
    status_code: Optional[int]
    success: bool
    error: Optional[str]
    elapsed_ms: float
    structured_error: Optional[dict] = field(default=None)


# ---------------------------------------------------------------------------
# AsyncFetcher
# ---------------------------------------------------------------------------


class AsyncFetcher:
    """
    Async HTTP fetcher with connection pooling and retry logic.

    Automatically falls back to httpx if aiohttp is not available,
    and to sync requests if neither is available.

    Parameters
    ----------
    max_concurrent : int
        Maximum number of simultaneous in-flight requests (semaphore cap).
    timeout : float
        Per-request timeout in seconds.
    max_retries : int
        Number of retry attempts for transient errors.
    retry_delay : float
        Base delay (seconds) for exponential back-off between retries.
    headers : dict, optional
        Default HTTP headers sent with every request.
    rate_limit_delay : float
        Extra sleep (seconds) inserted *before* each request inside
        ``fetch_many_async_with_cancel``.  Useful for GitHub sources where
        tight concurrent bursts trigger 429s.  Default: 0 (no extra delay).
    """

    def __init__(
        self,
        max_concurrent: int = 50,
        timeout: float = 10.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        headers: Optional[Dict[str, str]] = None,
        rate_limit_delay: float = 0.0,
    ):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.headers = headers or {}
        self.rate_limit_delay = rate_limit_delay

        if AIOHTTP_AVAILABLE:
            self.backend = "aiohttp"
        elif HTTPX_AVAILABLE:
            self.backend = "httpx"
        else:
            self.backend = "sync"
            logger.warning(
                "Neither aiohttp nor httpx available. "
                "Install with: pip install 'v2ray-finder[async]'"
            )

    # ------------------------------------------------------------------
    # aiohttp backend
    # ------------------------------------------------------------------

    async def _fetch_with_aiohttp(
        self,
        session: "aiohttp.ClientSession",
        url: str,
    ) -> FetchResult:
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                async with session.get(url) as response:
                    content = await response.text()
                    elapsed = (time.time() - start_time) * 1000

                    if response.status == 200:
                        return FetchResult(
                            url=url,
                            content=content,
                            status_code=response.status,
                            success=True,
                            error=None,
                            elapsed_ms=elapsed,
                        )
                    elif response.status in (403, 429):
                        msg, se = _rate_limit_error(url, response.status)
                        return FetchResult(
                            url=url,
                            content=None,
                            status_code=response.status,
                            success=False,
                            error=msg,
                            elapsed_ms=elapsed,
                            structured_error=se,
                        )
                    else:
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_delay * (2**attempt))
                            continue
                        msg, se = _http_error(url, response.status)
                        return FetchResult(
                            url=url,
                            content=None,
                            status_code=response.status,
                            success=False,
                            error=msg,
                            elapsed_ms=elapsed,
                            structured_error=se,
                        )

            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                elapsed = (time.time() - start_time) * 1000
                msg, se = _timeout_error(url)
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

            except aiohttp.ClientError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                elapsed = (time.time() - start_time) * 1000
                msg, se = _network_error(url, str(e))
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

            except Exception as e:
                elapsed = (time.time() - start_time) * 1000
                logger.error("Unexpected error fetching %s: %s", url, e)
                msg, se = _unknown_error(url, str(e))
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

        elapsed = (time.time() - start_time) * 1000
        msg, se = _network_error(url, "Max retries exceeded")
        return FetchResult(
            url=url,
            content=None,
            status_code=None,
            success=False,
            error=msg,
            elapsed_ms=elapsed,
            structured_error=se,
        )

    # ------------------------------------------------------------------
    # httpx backend
    # ------------------------------------------------------------------

    async def _fetch_with_httpx(
        self,
        client: "httpx.AsyncClient",
        url: str,
    ) -> FetchResult:
        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                response = await client.get(url)
                elapsed = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    return FetchResult(
                        url=url,
                        content=response.text,
                        status_code=response.status_code,
                        success=True,
                        error=None,
                        elapsed_ms=elapsed,
                    )
                elif response.status_code in (403, 429):
                    msg, se = _rate_limit_error(url, response.status_code)
                    return FetchResult(
                        url=url,
                        content=None,
                        status_code=response.status_code,
                        success=False,
                        error=msg,
                        elapsed_ms=elapsed,
                        structured_error=se,
                    )
                else:
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay * (2**attempt))
                        continue
                    msg, se = _http_error(url, response.status_code)
                    return FetchResult(
                        url=url,
                        content=None,
                        status_code=response.status_code,
                        success=False,
                        error=msg,
                        elapsed_ms=elapsed,
                        structured_error=se,
                    )

            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                elapsed = (time.time() - start_time) * 1000
                msg, se = _timeout_error(url)
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

            except httpx.HTTPError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
                    continue
                elapsed = (time.time() - start_time) * 1000
                msg, se = _network_error(url, str(e))
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

            except Exception as e:
                elapsed = (time.time() - start_time) * 1000
                logger.error("Unexpected error fetching %s: %s", url, e)
                msg, se = _unknown_error(url, str(e))
                return FetchResult(
                    url=url,
                    content=None,
                    status_code=None,
                    success=False,
                    error=msg,
                    elapsed_ms=elapsed,
                    structured_error=se,
                )

        elapsed = (time.time() - start_time) * 1000
        msg, se = _network_error(url, "Max retries exceeded")
        return FetchResult(
            url=url,
            content=None,
            status_code=None,
            success=False,
            error=msg,
            elapsed_ms=elapsed,
            structured_error=se,
        )

    # ------------------------------------------------------------------
    # fetch_many_async  (unchanged public API)
    # ------------------------------------------------------------------

    async def fetch_many_async(self, urls: List[str]) -> List[FetchResult]:
        if not urls:
            return []

        if self.backend == "aiohttp":
            timeout_obj = aiohttp.ClientTimeout(total=self.timeout)
            connector = aiohttp.TCPConnector(limit=self.max_concurrent)
            async with aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout_obj,
                connector=connector,
            ) as session:
                tasks = [self._fetch_with_aiohttp(session, url) for url in urls]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                return self._handle_gather_results(urls, results)

        elif self.backend == "httpx":
            limits = httpx.Limits(max_connections=self.max_concurrent)
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                limits=limits,
            ) as client:
                tasks = [self._fetch_with_httpx(client, url) for url in urls]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                return self._handle_gather_results(urls, results)

        else:
            raise RuntimeError(
                "fetch_many_async() requires aiohttp or httpx. "
                "Install with: pip install 'v2ray-finder[async]'. "
                "Use fetch_many() for automatic sync fallback."
            )

    # ------------------------------------------------------------------
    # V1-C3: fetch_many_async_with_cancel
    # ------------------------------------------------------------------

    async def fetch_many_async_with_cancel(
        self,
        urls: List[str],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> List[FetchResult]:
        """Fetch *urls* concurrently with early-cancel support.

        Unlike :meth:`fetch_many_async`, this coroutine:

        * Respects a shared ``cancel_event`` (``asyncio.Event``) — the moment
          the event is set, all pending tasks are cancelled immediately.
        * Inserts ``self.rate_limit_delay`` seconds of sleep before each
          request (semaphore-guarded), reducing burst pressure on
          rate-limited hosts (e.g. GitHub raw URLs).
        * Sets *cancel_event* itself when it receives a 403/429 response,
          so sibling tasks stop immediately without waiting for the full
          gather to finish.

        Parameters
        ----------
        urls:
            List of URLs to fetch.
        cancel_event:
            Shared ``asyncio.Event``.  Pass the same event to multiple
            ``fetch_many_async_with_cancel`` calls if you want one group
            to cancel the other on rate-limit.  A fresh event is created
            internally when *None* is given.

        Returns
        -------
        List of :class:`FetchResult` in the same order as *urls*.
        Cancelled tasks produce a ``FetchResult`` with ``success=False``
        and ``error='cancelled'``.
        """
        if not urls:
            return []

        if cancel_event is None:
            cancel_event = asyncio.Event()

        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: List[Optional[FetchResult]] = [None] * len(urls)

        async def _guarded(idx: int, url: str, **fetch_kwargs) -> None:
            if cancel_event.is_set():
                results[idx] = _cancelled_result(url)
                return
            async with semaphore:
                if cancel_event.is_set():
                    results[idx] = _cancelled_result(url)
                    return
                if self.rate_limit_delay > 0:
                    await asyncio.sleep(self.rate_limit_delay)
                fr = await fetch_kwargs["_fetch_fn"](url)
                # Fire cancel_event if rate-limited so siblings stop fast
                if fr.status_code in (403, 429):
                    logger.warning(
                        "[async_fetcher] Rate limit on %s (HTTP %d) — "
                        "cancelling remaining tasks.",
                        url,
                        fr.status_code,
                    )
                    cancel_event.set()
                results[idx] = fr

        if self.backend == "aiohttp":
            timeout_obj = aiohttp.ClientTimeout(total=self.timeout)
            connector = aiohttp.TCPConnector(limit=self.max_concurrent)
            async with aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout_obj,
                connector=connector,
            ) as session:

                async def _fetch_aio(url: str) -> FetchResult:
                    return await self._fetch_with_aiohttp(session, url)

                tasks = [
                    asyncio.ensure_future(
                        _guarded(i, url, _fetch_fn=_fetch_aio)
                    )
                    for i, url in enumerate(urls)
                ]
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    for t in tasks:
                        if not t.done():
                            t.cancel()

        elif self.backend == "httpx":
            limits = httpx.Limits(max_connections=self.max_concurrent)
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                limits=limits,
            ) as client:

                async def _fetch_httpx(url: str) -> FetchResult:
                    return await self._fetch_with_httpx(client, url)

                tasks = [
                    asyncio.ensure_future(
                        _guarded(i, url, _fetch_fn=_fetch_httpx)
                    )
                    for i, url in enumerate(urls)
                ]
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                finally:
                    for t in tasks:
                        if not t.done():
                            t.cancel()

        else:
            raise RuntimeError(
                "fetch_many_async_with_cancel() requires aiohttp or httpx."
            )

        # Fill any slots that never got a result (task cancelled before writing)
        for i, url in enumerate(urls):
            if results[i] is None:
                results[i] = _cancelled_result(url)

        return results  # type: ignore[return-value]

    @staticmethod
    def _handle_gather_results(
        urls: List[str],
        results: list,
    ) -> List[FetchResult]:
        """Wrap any bare exceptions from asyncio.gather into FetchResult."""
        out = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                msg, se = _unknown_error(urls[i], str(result))
                out.append(
                    FetchResult(
                        url=urls[i],
                        content=None,
                        status_code=None,
                        success=False,
                        error=msg,
                        elapsed_ms=0,
                        structured_error=se,
                    )
                )
            else:
                out.append(result)
        return out

    # ------------------------------------------------------------------
    # fetch_many (sync wrapper)
    # ------------------------------------------------------------------

    def fetch_many(self, urls: List[str]) -> List[FetchResult]:
        if self.backend == "sync":
            import requests

            results = []
            for url in urls:
                start_time = time.time()
                try:
                    response = requests.get(
                        url,
                        headers=self.headers,
                        timeout=self.timeout,
                    )
                    elapsed = (time.time() - start_time) * 1000
                    if response.status_code == 200:
                        results.append(
                            FetchResult(
                                url=url,
                                content=response.text,
                                status_code=response.status_code,
                                success=True,
                                error=None,
                                elapsed_ms=elapsed,
                            )
                        )
                    elif response.status_code in (403, 429):
                        msg, se = _rate_limit_error(url, response.status_code)
                        results.append(
                            FetchResult(
                                url=url,
                                content=None,
                                status_code=response.status_code,
                                success=False,
                                error=msg,
                                elapsed_ms=elapsed,
                                structured_error=se,
                            )
                        )
                    else:
                        msg, se = _http_error(url, response.status_code)
                        results.append(
                            FetchResult(
                                url=url,
                                content=None,
                                status_code=response.status_code,
                                success=False,
                                error=msg,
                                elapsed_ms=elapsed,
                                structured_error=se,
                            )
                        )
                except requests.exceptions.Timeout:
                    elapsed = (time.time() - start_time) * 1000
                    msg, se = _timeout_error(url)
                    results.append(
                        FetchResult(
                            url=url,
                            content=None,
                            status_code=None,
                            success=False,
                            error=msg,
                            elapsed_ms=elapsed,
                            structured_error=se,
                        )
                    )
                except Exception as e:
                    elapsed = (time.time() - start_time) * 1000
                    msg, se = _network_error(url, str(e))
                    results.append(
                        FetchResult(
                            url=url,
                            content=None,
                            status_code=None,
                            success=False,
                            error=msg,
                            elapsed_ms=elapsed,
                            structured_error=se,
                        )
                    )
            return results

        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run, self.fetch_many_async(urls)
                        )
                        return future.result()
                else:
                    return loop.run_until_complete(self.fetch_many_async(urls))
            except RuntimeError:
                return asyncio.run(self.fetch_many_async(urls))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cancelled_result(url: str) -> FetchResult:
    """Produce a FetchResult representing a task cancelled due to rate-limit."""
    msg, se = _rate_limit_error(url, 429)
    return FetchResult(
        url=url,
        content=None,
        status_code=None,
        success=False,
        error="cancelled",
        elapsed_ms=0.0,
        structured_error={
            "error_type": "rate_limit_exceeded",
            "message": "Request cancelled — upstream rate limit detected.",
            "details": {"reason": "sibling_rate_limited"},
        },
    )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def fetch_urls_concurrently(
    urls: List[str],
    max_concurrent: int = 50,
    timeout: float = 10.0,
    headers: Optional[Dict[str, str]] = None,
) -> List[FetchResult]:
    fetcher = AsyncFetcher(
        max_concurrent=max_concurrent,
        timeout=timeout,
        headers=headers,
    )
    return fetcher.fetch_many(urls)
