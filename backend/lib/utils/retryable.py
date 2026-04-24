import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

_R = TypeVar("_R")


async def retryable_with_backoff(
    coro_factory: Callable[[], Awaitable[_R]],
    retryable: tuple[type[Exception], ...],
    max_attempts: int,
    base_delay: float,
) -> _R:
    """
    Tiny helper that retries *async* operations with decorrelated jitter.
    """
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except asyncio.CancelledError:
            logging.warning(
                "[retryable] received asyncio.CancelledError, re-raising...",
            )
            raise  # Don't retry on cancellation
        except retryable as e:
            attempt += 1
            if attempt >= max_attempts:
                logging.warning(
                    f"[retryable] max attempt reached. Raising e: {e}",
                )
                raise

            # jitter
            sleep = random.uniform(0, base_delay * 2**attempt)
            logging.warning(
                f"[retryable] call failed, retrying in {sleep}s (attempt {attempt}/{max_attempts}), e: {e}",
            )
            await asyncio.sleep(sleep)
        except Exception as e:
            logging.warning(
                f"[retryable] not a retryable error. Raising: {type(e)}, {e}",
            )
            raise  # Not a retryable error, propagate immediately
