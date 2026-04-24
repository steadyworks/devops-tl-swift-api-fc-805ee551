import asyncio
import logging
import random
import time
from asyncio import Lock, Semaphore
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from backend.env_loader import EnvLoader

from .radar_models import RadarReverseGeocodeResponse

_R = TypeVar("_R")


class RadarHttpClient:
    BASE_URL: str = "https://api.radar.io/v1"
    RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (httpx.RequestError,)

    def __init__(
        self,
        max_retries: int = 3,
        base_backoff: float = 0.2,
        max_concurrent_requests: int = 5,
        rate_limit_qps: int = 10,
    ) -> None:
        self.api_key: str = EnvLoader.get("RADAR_MAPPING_API_PUBLISHABLE_API_KEY")
        self.max_retries: int = max_retries
        self.base_backoff: float = base_backoff
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": self.api_key},
            timeout=httpx.Timeout(
                connect=3.0,  # quick fail for unreachable hosts
                read=10.0,  # wait time for response
                write=10.0,  # wait time for sending data
                pool=5.0,  # wait time for connection from pool
            ),
            follow_redirects=True,
        )
        self._semaphore = Semaphore(max_concurrent_requests)

        self.rate_limit_qps = rate_limit_qps  # Target QPS
        self._min_interval = 1.0 / self.rate_limit_qps  # e.g. 0.1s between requests
        self._last_request_time: float = (
            time.monotonic()
        )  # Epoch timestamp of last request
        self._rate_limit_lock = Lock()  # To ensure serialized access

    async def close(self) -> None:
        """Close the underlying HTTPX client."""
        if not self._client.is_closed:  # Defensive check
            await self._client.aclose()

    async def reverse_geocode(
        self, lat: float, lng: float
    ) -> RadarReverseGeocodeResponse:
        """Reverse geocode coordinates to address using Radar API."""

        async def call() -> dict[str, Any]:
            response: httpx.Response = await self._client.get(
                "/geocode/reverse",
                params={
                    "coordinates": f"{lat},{lng}",
                    "layers": "fine",
                },
            )
            response.raise_for_status()
            return response.json()

        raw = await self._retryable(call)
        logging.debug(raw)
        return RadarReverseGeocodeResponse.model_validate(raw)

    async def _retryable(self, coro_factory: Callable[[], Awaitable[_R]]) -> _R:
        attempt: int = 0
        while True:
            try:
                async with self._semaphore:
                    async with self._rate_limit_lock:
                        now = time.monotonic()
                        elapsed = now - self._last_request_time
                        if elapsed < self._min_interval:
                            await asyncio.sleep(self._min_interval - elapsed)
                        self._last_request_time = time.monotonic()

                    return await coro_factory()

            except asyncio.CancelledError:
                logging.warning("[radar] CancelledError received. Propagating.")
                raise
            except self.RETRYABLE_EXCEPTIONS as e:
                attempt += 1
                if attempt >= self.max_retries:
                    logging.warning(f"[radar] Max retries reached. Raising: {e}")
                    raise RuntimeError("Radar request failed after retries") from e

                delay: float = random.uniform(0, self.base_backoff * 2**attempt)
                logging.warning(
                    f"[radar] Retryable error: {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.2f}s (attempt {attempt}/{self.max_retries})"
                )
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"Radar API HTTP error: {e.response.status_code} - {e.response.text}"
                ) from e
            except Exception as e:
                logging.error(f"[radar] Unexpected error: {type(e).__name__}: {e}")
                raise
