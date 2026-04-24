import asyncio
import shutil
import socket
from pathlib import Path

from backend.lib.types.asset import Asset, AssetStorageKey
from backend.path_manager import PathManager

from .base import AssetManager


class LocalAssetManager(AssetManager):
    def __init__(self, root_dir: Path = PathManager().get_assets_root()):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def upload_file(
        self,
        src_file_path: Path,
        dest_key: AssetStorageKey,
    ) -> Asset:
        dest_path = self.root_dir / dest_key
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy, src_file_path, dest_path)
        return Asset(
            cached_local_path=src_file_path,
            asset_storage_key=dest_key,
        )

    async def download_file(
        self, src_key: AssetStorageKey, dest_file_path: Path
    ) -> Asset:
        src_path = self.root_dir / src_key
        dest_file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy, src_path, dest_file_path)
        return Asset(
            cached_local_path=dest_file_path,
            asset_storage_key=src_key,
        )

    async def generate_signed_url(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        # No real signing; just return a URL FastAPI can serve locally
        return f"http://{local_ip}:8000/assets/{src_key}"

    async def generate_signed_url_put(
        self, src_key: AssetStorageKey, expires_in: int = 3600
    ) -> str:
        # No real signing; just return a URL FastAPI can serve locally
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return f"http://{local_ip}:8000/api/dev/asset_upload/{src_key}"
