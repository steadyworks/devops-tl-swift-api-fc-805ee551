from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from backend.db.dal import DALAssets
from backend.db.dal.schemas import DAOAssetsCreate
from backend.db.data_models import AssetUploadStatus, DAOAssets


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.mark.asyncio
async def test_create_asset_with_metadata(db_session: AsyncSession) -> None:
    # Arrange
    metadata = {"camera": "nikon", "location": "paris"}
    asset_create = DAOAssetsCreate(
        owner_id=uuid4(),
        asset_key_original="original.jpg",
        asset_key_display="display.jpg",
        asset_key_llm="llm.jpg",
        metadata_json=metadata,  # passed using alias="metadata"
        original_photobook_id=None,
        upload_status=AssetUploadStatus.PENDING,
    )

    # Act
    result: DAOAssets = await DALAssets.create(db_session, asset_create)
    await db_session.commit()

    # Assert
    assert isinstance(result, DAOAssets)
    assert result.asset_key_original == "original.jpg"
    assert result.metadata_json == metadata
    assert result.created_at is not None
    assert isinstance(result.created_at, datetime)
    assert result.created_at.tzinfo is None or result.created_at.tzinfo == timezone.utc

    # Additional DB-level check if needed:
    db_obj = await db_session.get(DAOAssets, result.id)
    assert db_obj is not None
    assert db_obj.metadata_json == metadata
