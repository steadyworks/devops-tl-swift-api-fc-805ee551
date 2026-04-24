import os
import threading
from typing import Final, Optional

from dotenv import load_dotenv

from backend.path_manager import PathManager


class EnvLoader:
    _lock: Final[threading.Lock] = threading.Lock()
    _loaded: bool = False
    _env_file_path: Optional[str] = None

    @classmethod
    def _load_env_once(cls) -> None:
        with cls._lock:
            if not cls._loaded:
                env = os.getenv("ENV")
                env_file = ".env.prod" if env == "production" else ".env.dev"
                env_path = PathManager().get_repo_root() / env_file
                cls._env_file_path = str(env_path)

                loaded = load_dotenv(dotenv_path=env_path)
                if not loaded:
                    raise RuntimeError(
                        f"Failed to load environment from {env_path}"
                    )

                cls._loaded = True

    @classmethod
    def reload_env(cls) -> None:
        with cls._lock:
            if cls._env_file_path:
                load_dotenv(dotenv_path=cls._env_file_path, override=True)
            else:
                # Reload fallback
                cls._loaded = False
                cls._load_env_once()

    @classmethod
    def get(cls, key: str, default_value: Optional[str] = None) -> str:
        cls._load_env_once()
        val = os.getenv(key)
        if val is None:
            if default_value is not None:
                return default_value
            raise KeyError(f"Missing environment variable: {key}")
        return val

    @classmethod
    def get_optional(cls, key: str) -> Optional[str]:
        cls._load_env_once()
        return os.getenv(key)

    @classmethod
    def is_production(cls) -> bool:
        env = cls.get("ENV", "development").lower()
        return env == "production"

    @classmethod
    def is_development(cls) -> bool:
        return not cls.is_production()

    @classmethod
    def is_debug_bypass_auth_enabled(cls) -> bool:
        return True
        return cls.get("DEBUG_BYPASS_AUTH", "false").lower() == "true"
