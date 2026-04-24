# backend/lib/asset_manager/s3_async.py
import asyncio
import atexit
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client

from backend.env_loader import EnvLoader
from backend.lib.types.asset import Asset, AssetStorageKey
from backend.lib.utils.retryable import retryable_with_backoff

from .base import AssetManager

__all__ = ["S3AssetManager"]

# --------------------------------------------------------------------------- #
# Global resources – one per *process*
# --------------------------------------------------------------------------- #

# Tunable knobs
_MAX_THREADS = 64
_MAX_POOL_CONNECTIONS = 64
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30


# Reasonable process-wide caps; override in env if needed
_MAX_CONCURRENT_UPLOADS = 15
_MAX_CONCURRENT_DOWNLOADS = 30
_MAX_S3_TIMEOUT_OP = 30

_CLIENT_TTL_SECS = 900 + random.randint(-60, 60)  # 15 min
_REFRESH_LOCK = asyncio.Lock()  # shared

# Dedicated executor for every blocking S3 call
_S3_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_THREADS,
    thread_name_prefix="s3-io",
)

# Ensure we tear the pool down when the process exits

atexit.register(_S3_EXECUTOR.shutdown, wait=True)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_R = TypeVar("_R")


async def _run_in_s3_pool(fn: Callable[..., _R], *args: Any, **kwargs: Any) -> _R:
    """
    Utility that schedules *fn* on the dedicated S3 thread-pool
    instead of the default asyncio executor.
    """
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_S3_EXECUTOR, lambda: fn(*args, **kwargs)),
        timeout=_MAX_S3_TIMEOUT_OP,  # add upper-bound timeout
    )


# --------------------------------------------------------------------------- #
# Concrete implementation
# --------------------------------------------------------------------------- #


class S3AssetManager(AssetManager):
    """
    Production-grade async wrapper around boto3.S3 with:
        • dedicated thread-pool
        • per-op semaphores (fair sharing across coroutines)
        • exponential-back-off retries
        • short, explicit HTTP time-outs
    """

    # Shared across every instance in the process
    _upload_sem = asyncio.Semaphore(_MAX_CONCURRENT_UPLOADS)
    _download_sem = asyncio.Semaphore(_MAX_CONCURRENT_DOWNLOADS)

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
    ) -> None:
        self.bucket_name = bucket_name or EnvLoader.get("AWS_S3_DEFAULT_BUCKET_NAME")
        self.region_name = region_name or EnvLoader.get("AWS_S3_DEFAULT_BUCKET_REGION")
        self._new_client()  # ⟵ first incarnation

    def _new_client(self) -> None:
        """Build a brand-new boto3 client and remember its birthday."""
        self._born = time.monotonic()
        self.s3: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            region_name=self.region_name,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                max_pool_connections=_MAX_POOL_CONNECTIONS,
                connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                read_timeout=_READ_TIMEOUT_SECONDS,
            ),
        )

    async def _maybe_refresh_client(self) -> None:
        age = time.monotonic() - self._born
        if age < _CLIENT_TTL_SECS:
            return
        async with _REFRESH_LOCK:
            # re-check after acquiring
            if time.monotonic() - self._born >= _CLIENT_TTL_SECS:
                logging.info("[s3] Recycling S3 client")
                try:
                    await _run_in_s3_pool(self.s3.close)
                except Exception as exc:
                    logging.debug(
                        "Ignoring error when closing stale S3 client: %s", exc
                    )
                self._new_client()

    # --------------------------- uploads ---------------------------------- #

    async def upload_file(
        self,
        src_file_path: Path,
        dest_key: AssetStorageKey,
    ) -> Asset:
        await self._maybe_refresh_client()
        async with self._upload_sem:

            async def _single_upload() -> Asset:
                asset = Asset(
                    cached_local_path=src_file_path,
                    asset_storage_key=dest_key,
                )
                await _run_in_s3_pool(
                    self.s3.upload_file,
                    str(src_file_path),
                    self.bucket_name,
                    dest_key,
                    ExtraArgs={"ContentType": await asset.mime_type()},
                )
                return asset

            return await retryable_with_backoff(
                _single_upload,
                retryable=(ClientError,),
                max_attempts=3,
                base_delay=0.5,
            )

    # -------------------------- downloads --------------------------------- #

    async def download_file(
        self, src_key: AssetStorageKey, dest_file_path: Path
    ) -> Asset:
        await self._maybe_refresh_client()
        async with self._download_sem:

            async def _single_download() -> Asset:
                await _run_in_s3_pool(
                    self.s3.download_file,
                    self.bucket_name,
                    src_key,
                    str(dest_file_path),
                )
                return Asset(
                    cached_local_path=dest_file_path,
                    asset_storage_key=src_key,
                )

            return await retryable_with_backoff(
                _single_download,
                retryable=(ClientError,),
                max_attempts=3,
                base_delay=0.5,
            )

    # ---------------------- presigned URLs -------------------------------- #

    async def generate_signed_url(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str:
        await self._maybe_refresh_client()
        return await _run_in_s3_pool(
            self.s3.generate_presigned_url,
            ClientMethod="get_object",
            Params={"Bucket": self.bucket_name, "Key": src_key},
            ExpiresIn=expires_in,
        )

    async def generate_signed_url_put(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str:
        await self._maybe_refresh_client()
        return await _run_in_s3_pool(
            self.s3.generate_presigned_url,
            ClientMethod="put_object",
            Params={"Bucket": self.bucket_name, "Key": src_key},
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
