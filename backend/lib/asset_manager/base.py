import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

from backend.lib.types.asset import Asset, AssetStorageKey


class AssetManager(ABC):
    def mint_asset_key_for_presigned_slots(
        self,
        user_id: UUID,
        safe_filename: str,
    ) -> AssetStorageKey:
        return f"uploads/users/{user_id}/{safe_filename}"

    def mint_asset_key(
        self,
        photobook_id: UUID,
        safe_filename: str,
    ) -> AssetStorageKey:
        return f"uploads/{photobook_id}/{safe_filename}"

    @abstractmethod
    async def upload_file(
        self,
        src_file_path: Path,
        dest_key: AssetStorageKey,
    ) -> Asset: ...

    async def upload_files_batched(
        self,
        upload_requests: list[
            tuple[Path, AssetStorageKey]
        ],  # [(src_file_path, dest_key)]
    ) -> dict[Path, Asset | Exception]:
        success: dict[Path, Asset] = {}
        failed: dict[Path, Exception] = {}

        async def safe_upload(_src_file_path: Path, _dest_key: AssetStorageKey) -> None:
            try:
                asset = await self.upload_file(
                    src_file_path=_src_file_path,
                    dest_key=_dest_key,
                )
                success[_src_file_path] = asset
            except Exception as e:
                msg = f"Failed to upload {_src_file_path} → {_dest_key}: {e}"
                logging.warning(msg)
                failed[_src_file_path] = e

        await asyncio.gather(
            *[
                safe_upload(src_file_path, dest_key)
                for (src_file_path, dest_key) in upload_requests
            ]
        )
        return success | failed

    @abstractmethod
    async def download_file(
        self,
        src_key: AssetStorageKey,
        dest_file_path: Path,
    ) -> Asset: ...

    async def download_files_batched(
        self,
        download_requests: list[
            tuple[AssetStorageKey, Path]
        ],  # [(src_key, dest_file_path)]
    ) -> dict[AssetStorageKey, Asset | Exception]:
        success: dict[AssetStorageKey, Asset] = {}
        failed: dict[AssetStorageKey, Exception] = {}

        async def safe_download(
            _src_key: AssetStorageKey, _dest_file_path: Path
        ) -> None:
            try:
                asset = await self.download_file(
                    src_key=_src_key,
                    dest_file_path=_dest_file_path,
                )
                success[_src_key] = asset
            except Exception as e:
                msg = f"Failed to download {_src_key} → {_dest_file_path}: {e}"
                logging.warning(msg)
                failed[_src_key] = e

        await asyncio.gather(
            *[
                safe_download(src_key, dest_file_path)
                for (src_key, dest_file_path) in download_requests
            ]
        )
        return success | failed

    @abstractmethod
    async def generate_signed_url(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str: ...

    @abstractmethod
    async def generate_signed_url_put(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str: ...

    async def generate_signed_urls_batched(
        self, src_keys: list[AssetStorageKey], expires_in: int = 3600
    ) -> dict[AssetStorageKey, str | Exception]:
        success: dict[AssetStorageKey, str] = {}
        failed: dict[AssetStorageKey, Exception] = {}

        async def safe_sign(_src_key: AssetStorageKey, _expires_in: int) -> None:
            try:
                url = await self.generate_signed_url(
                    src_key=_src_key, expires_in=_expires_in
                )
                success[_src_key] = url
            except Exception as e:
                msg = f"Failed to generate signed URL for {_src_key}: {e}"
                logging.warning(msg)
                failed[_src_key] = e

        await asyncio.gather(*[safe_sign(src_key, expires_in) for src_key in src_keys])
        return success | failed
