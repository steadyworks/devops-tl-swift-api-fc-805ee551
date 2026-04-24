from __future__ import annotations

import asyncio

import pytest

from backend.lib.utils.retryable import (
    retryable_with_backoff,  # replace with actual import
)


class CustomRetryableError(Exception):
    pass


class CustomNonRetryableError(Exception):
    pass


@pytest.mark.asyncio
async def test_succeeds_immediately() -> None:
    async def task() -> str:
        return "success"

    result: str = await retryable_with_backoff(
        coro_factory=task,
        retryable=(CustomRetryableError,),
        max_attempts=3,
        base_delay=0.01,
    )
    assert result == "success"


@pytest.mark.asyncio
async def test_retries_then_succeeds() -> None:
    calls: list[str] = []

    async def task() -> str:
        if len(calls) < 2:
            calls.append("fail")
            raise CustomRetryableError("try again")
        return "recovered"

    result: str = await retryable_with_backoff(
        coro_factory=task,
        retryable=(CustomRetryableError,),
        max_attempts=5,
        base_delay=0.01,
    )
    assert result == "recovered"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_raises_after_max_attempts() -> None:
    attempts: int = 0

    async def task() -> str:
        nonlocal attempts
        attempts += 1
        raise CustomRetryableError("persistent failure")

    with pytest.raises(CustomRetryableError):
        await retryable_with_backoff(
            coro_factory=task,
            retryable=(CustomRetryableError,),
            max_attempts=3,
            base_delay=0.01,
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_non_retryable_exception_raises_immediately() -> None:
    async def task() -> str:
        raise CustomNonRetryableError("fatal")

    with pytest.raises(CustomNonRetryableError):
        await retryable_with_backoff(
            coro_factory=task,
            retryable=(CustomRetryableError,),  # doesn't match
            max_attempts=5,
            base_delay=0.01,
        )


@pytest.mark.asyncio
async def test_cancelled_error_is_propagated() -> None:
    async def task() -> str:
        raise asyncio.CancelledError("cancelled")

    with pytest.raises(asyncio.CancelledError):
        await retryable_with_backoff(
            coro_factory=task,
            retryable=(CustomRetryableError,),
            max_attempts=5,
            base_delay=0.01,
        )
