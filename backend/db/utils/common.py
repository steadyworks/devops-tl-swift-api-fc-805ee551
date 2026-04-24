import logging
from typing import Literal

from backend.db.data_models import DAOAssets
from backend.lib.types.asset import AssetStorageKey


def retrieve_available_asset_key_in_order_of(
    dao: DAOAssets,
    preference_order: list[
        Literal[
            "asset_key_original",
            "asset_key_display",
            "asset_key_llm",
            "asset_key_thumbnail",
        ]
    ],
) -> AssetStorageKey:
    primary = True
    for attr in preference_order:
        asset_key = getattr(dao, attr)
        if asset_key is not None:
            return asset_key
        if primary:
            logging.warning(f"Primary asset key {attr} unavailable for asset {dao.id}")
            primary = False

    raise Exception(f"No asset keys available for asset {dao.id}")
