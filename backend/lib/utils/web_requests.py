import asyncio
import logging
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, List, Optional, TypeVar

from fastapi import UploadFile

from backend.lib.types.asset import Asset

UserOriginalFileName = str


@dataclass
class TempUploadEntry:
    original_filename: UserOriginalFileName
    absolute_path: Path


@dataclass
class TempUploadsMetadata:
    root_dir: Path
    files: list[TempUploadEntry]


async def save_uploads_to_tempdir(
    upload_files: list[UploadFile],
    tmp_root: Path = Path("/tmp"),
) -> TempUploadsMetadata:
    temp_dir = tmp_root / uuid.uuid4().hex

    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_entries: list[TempUploadEntry] = []

    for upload_file in upload_files:
        original_name = upload_file.filename or f"unnamed_{uuid.uuid4().hex}.bin"
        ext = Path(original_name).suffix or ".bin"
        safe_name = f"{uuid.uuid4().hex}{ext}"
        temp_path = temp_dir / safe_name
        contents = await upload_file.read()

        def write_bytes(_path: Path, _data: bytes) -> None:
            with open(_path, "wb") as f:
                f.write(_data)

        await asyncio.to_thread(write_bytes, temp_path, contents)

        temp_file_entries.append(
            TempUploadEntry(original_filename=original_name, absolute_path=temp_path)
        )

    return TempUploadsMetadata(root_dir=temp_dir, files=temp_file_entries)


def cleanup_tempdir(temp_dir: Path) -> None:
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as e:
        logging.warning(f"Failed to cleanup tempdir {temp_dir}: {e}")


class UploadFileTempDirManager:
    def __init__(
        self, job_id: str, upload_files: List[UploadFile], tmp_root: Path = Path("/tmp")
    ):
        self.upload_files = upload_files
        self.tmp_root = tmp_root
        self.temp_dir: Path = tmp_root / job_id
        self.managed_assets: list[tuple[UserOriginalFileName, Asset]] = []

    async def __aenter__(self) -> list[tuple[UserOriginalFileName, Asset]]:
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        for upload_file in self.upload_files:
            # Fallbacks for missing filename or content_type
            original_name = upload_file.filename or f"unnamed_{uuid.uuid4().hex}.bin"
            ext = Path(original_name).suffix or ".bin"
            safe_name = f"{uuid.uuid4().hex}{ext}"
            temp_path = self.temp_dir / safe_name
            contents = await upload_file.read()

            def write_bytes_to_file(_path: Path, _data: bytes) -> None:
                with open(_path, "wb") as f:
                    f.write(_data)

            await asyncio.to_thread(write_bytes_to_file, temp_path, contents)
            self.managed_assets.append(
                (
                    original_name,
                    Asset(
                        cached_local_path=temp_path,
                        asset_storage_key=None,
                    ),
                )
            )

        return self.managed_assets

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        return None


_T = TypeVar("_T", bound=BaseException)


class AsyncTempDir:
    """
    Async context manager that creates a unique temporary directory and
    cleans it up on exit (unless instructed to keep it).

    Example
    -------
    async with AsyncTempDir(prefix="upload_") as tmp:
        file_path = tmp / "example.png"
        ...

    Notes
    -----
    * All blocking filesystem work happens in a background thread via
      `asyncio.to_thread`, so it won’t block the event loop.
    * Pass `keep=True` if you need to inspect the directory after exit
      (e.g., during debugging or on failure).
    """

    __slots__ = (
        "_prefix",
        "_suffix",
        "_base_dir",
        "_keep",
        "_path",
    )

    def __init__(
        self,
        *,
        prefix: str = "tmp_",
        suffix: str = "",
        dir: Optional[str | Path] = None,
        keep: bool = False,
    ) -> None:
        self._prefix = prefix
        self._suffix = suffix
        self._base_dir = Path(dir) if dir else None
        self._keep = keep
        self._path: Optional[Path] = None

    # Public attribute for callers
    @property
    def path(self) -> Path:
        if self._path is None:
            raise RuntimeError("Temp dir not yet created.")
        return self._path

    # ------------------------------------------------------------------ #
    # Async context-manager protocol
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> Path:
        def _mkdtemp() -> str:
            return tempfile.mkdtemp(
                prefix=self._prefix,
                suffix=self._suffix,
                dir=str(self._base_dir) if self._base_dir else None,
            )

        tmp_str: str = await asyncio.to_thread(_mkdtemp)
        self._path = Path(tmp_str)
        return self._path

    async def __aexit__(
        self,
        exc_type: Optional[type[_T]],
        exc: Optional[_T],
        tb: Optional[Any],
    ) -> bool:
        if self._keep:
            logging.debug("Keeping temp dir at %s", self._path)
            return False  # propagate any exception

        if self._path and self._path.exists():
            await asyncio.to_thread(shutil.rmtree, self._path, ignore_errors=True)

        # Returning False means any exception inside the block is re-raised
        return False


# Convenience factory function — feels nicer to call.
def async_tempdir(
    *,
    prefix: str = "tmp_",
    suffix: str = "",
    dir: Optional[str | Path] = None,
    keep: bool = False,
) -> AsyncTempDir:
    return AsyncTempDir(prefix=prefix, suffix=suffix, dir=dir, keep=keep)
