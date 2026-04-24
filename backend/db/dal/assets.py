import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import AssetUploadStatus, DAOAssets

from .base import AsyncPostgreSQLDAL
from .schemas import DAOAssetsCreate, DAOAssetsUpdate


class DALAssets(AsyncPostgreSQLDAL[DAOAssets, DAOAssetsCreate, DAOAssetsUpdate]):
    model = DAOAssets

    @classmethod
    async def bulk_update_status_where_pending(
        cls,
        session: AsyncSession,
        asset_ids: set[UUID],
        owner_id: UUID,
        new_status: AssetUploadStatus,  # e.g. AssetUploadStatus.SUCCEEDED
        current_matching_status: AssetUploadStatus,  # e.g. AssetUploadStatus.PENDING
    ) -> list[UUID]:
        """
        Bulk update asset statuses only if they are currently in a given state (e.g., PENDING).
        This is idempotent and prevents redundant writes.

        Args:
            session: Active DB session.
            asset_ids: UUIDs to update.
            user_id: Ensure assets belong to this user.
            new_status: Target status to set.
            current_status: Only update rows currently in this status.
        """
        if not asset_ids:
            return []

        try:
            id_col = getattr(cls.model, "id")
            owner_col = getattr(cls.model, "owner_id")
            status_col = getattr(cls.model, "upload_status")

            stmt = (
                (
                    update(cls.model)
                    .where(
                        id_col.in_(asset_ids),
                        owner_col == owner_id,
                        status_col == current_matching_status,
                    )
                    .values(
                        upload_status=new_status,
                    )
                )
                .returning(id_col)
                .execution_options(synchronize_session=False)
            )

            result = await session.execute(stmt)
            updated_ids: list[UUID] = [row[0] for row in result.fetchall()]

            # logging.info(
            #     f"[DAL] Updated {result.rowcount} assets to {new_status} "  # type: ignore
            #     f"for user {user_id}, filtered from {len(asset_ids)} attempted."
            # )
            return updated_ids
        except Exception:
            logging.exception("bulk_update_status_if_pending failed.")
            raise
