import logging
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Literal

from .types import CompressionTier

AssetKeyType = Literal[
    "asset_key_original", "asset_key_display", "asset_key_llm", "asset_key_thumbnail"
]

MIN_FREE_DISK_BYTES = 100 * 1024 * 1024  # 100MB


@contextmanager
def compression_tier_tempdir(
    tier: CompressionTier,
    root_path: Path,
) -> Generator[Path, None, None]:
    """
    Creates a temporary output subdirectory for a given compression tier,
    and cleans it up on exit.
    """
    tempdir = root_path / f"compressed_{tier.value}_{uuid.uuid4().hex}"
    tempdir.mkdir(parents=True, exist_ok=True)

    try:
        yield tempdir
    finally:
        try:
            shutil.rmtree(tempdir, ignore_errors=True)
        except Exception as e:
            logging.warning(f"[TempDir] Failed to clean up {tempdir}: {e}")


class CompressUploadMixin:
    @classmethod
    def _get_asset_key_type_by_compression_tier(
        cls, compression_tier: CompressionTier
    ) -> AssetKeyType:
        if compression_tier == CompressionTier.HIGH_END_DISPLAY:
            return "asset_key_display"
        elif compression_tier == CompressionTier.LLM:
            return "asset_key_llm"
        else:
            raise Exception("Only asset_key_display and asset_key_llm supported")

    @classmethod
    def _sanity_check_free_storage(
        cls,
        root_dir: Path,
    ) -> tuple[bool, str]:  # (should_abort, error_message)
        should_abort, error_message = False, ""
        free_bytes = shutil.disk_usage(root_dir).free
        if free_bytes < MIN_FREE_DISK_BYTES:
            should_abort = True
            error_message = (
                f"[CompressUploadMixin] Not enough free disk space in {root_dir} "
                f"({free_bytes / (1024**2):.2f} MB available)"
            )
        return should_abort, error_message
