import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import magic

from backend.lib.utils.common import none_throws


@dataclass
class Asset:
    cached_local_path: Optional[Path]
    asset_storage_key: Optional[str]
    __real_mime_type: Optional[str] = field(default=None, init=False, repr=False)

    async def mime_type(self, max_bytes: int = 4096) -> str:
        """
        Lazily compute and cache the real MIME type from file content.

        Args:
            max_bytes (int): Max bytes to read for detection.

        Returns:
            str: The detected MIME type.
        """
        if self.__real_mime_type is not None:
            return self.__real_mime_type

        def _read_head() -> bytes:
            with none_throws(self.cached_local_path).open("rb") as f:
                return f.read(max_bytes)

        chunk = await asyncio.to_thread(_read_head)
        mime = magic.from_buffer(chunk, mime=True)

        if not mime:
            raise ValueError(
                f"Could not detect MIME type for: {self.cached_local_path}"
            )

        self._real_mime_type = mime
        return mime


AssetStorageKey = str
