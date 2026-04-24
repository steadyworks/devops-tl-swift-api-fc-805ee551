import logging

from backend.env_loader import EnvLoader

from .base import AssetManager
from .local import LocalAssetManager
from .s3 import S3AssetManager


class AssetManagerFactory:
    def create(self) -> AssetManager:
        if EnvLoader.is_production():
            logging.info("Using S3AssetManager under env production")
            return S3AssetManager()
        else:
            logging.info("Using LocalAssetManager under env development")
            return LocalAssetManager()
