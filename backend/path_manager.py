import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def __get_repo_root() -> Path:
    """Returns the path to the directory where this file (utils.py) resides."""
    return Path(__file__).resolve().parent


ROOT_DIR = __get_repo_root()
DEFAULT_LOCAL_ASSET_ROOT = "/tmp/timelens_assets/"


class PathManager:
    _instance = None

    def __new__(cls) -> "PathManager":
        if cls._instance is None:
            cls._instance = super(PathManager, cls).__new__(cls)
            cls._instance._init_paths()
        return cls._instance

    def _init_paths(self) -> None:
        os.makedirs(DEFAULT_LOCAL_ASSET_ROOT, exist_ok=True)

    def get_repo_root(self) -> Path:
        return ROOT_DIR

    def get_assets_root(self) -> Path:
        return Path(DEFAULT_LOCAL_ASSET_ROOT)
