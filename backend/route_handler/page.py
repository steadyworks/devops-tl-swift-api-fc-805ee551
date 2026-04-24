from typing import Optional
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALAssets,
    DALPages,
    DALPagesAssetsRel,
    DAOPagesAssetsRelCreate,
    DAOPagesAssetsRelUpdate,
    DAOPagesUpdate,
    FilterOp,
    OrderDirection,
    locked_row_by_id,
    safe_commit,
    safe_transaction,
)
from backend.db.data_models import DAOPages
from backend.db.externals import (
    AssetsOverviewResponse,
    PagesAssetsRelOverviewResponse,
    PagesOverviewResponse,
)
from backend.lib.asset_manager.base import AssetManager
from backend.route_handler.base import RouteHandler

from .base import enforce_response_model


class PageEditUserMessageRequest(BaseModel):
    user_message: str


class PhotoSlotItem(BaseModel):
    assetRelId: Optional[UUID]  # None implies newly added asset to the page
    assetId: UUID
    order: int


class PatchPhotoSlotsRequest(BaseModel):
    slots: list[PhotoSlotItem]


class PagesFullResponse(PagesOverviewResponse):
    assets: list[AssetsOverviewResponse]
    page_asset_rels: list[PagesAssetsRelOverviewResponse]

    @classmethod
    async def rendered_from_daos(
        cls,
        pages: list[DAOPages],
        db_session: AsyncSession,
        asset_manager: AssetManager,
    ) -> list["PagesFullResponse"]:
        page_ids = [page.id for page in pages]
        page_asset_rels = await DALPagesAssetsRel.list_all(
            db_session,
            filters={"page_id": (FilterOp.IN, page_ids)},
            order_by=[("order_index", OrderDirection.ASC)],
        )

        # Step 4: Collect all asset_ids used
        asset_ids = [rel.asset_id for rel in page_asset_rels if rel.asset_id]
        asset_daos = await DALAssets.get_by_ids(db_session, asset_ids)
        asset_overall_resps = await AssetsOverviewResponse.rendered_from_daos(
            asset_daos, asset_manager
        )
        asset_overall_resps_by_id = {resp.id: resp for resp in asset_overall_resps}

        # Step 6: Assemble response
        page_id_to_assets: dict[UUID, list[AssetsOverviewResponse]] = {}
        page_id_to_asset_rels: dict[UUID, list[PagesAssetsRelOverviewResponse]] = {}

        for rel in page_asset_rels:
            if rel.page_id and rel.asset_id:
                # Inject signed URL into the model
                asset_resp = asset_overall_resps_by_id[rel.asset_id]
                page_id_to_assets.setdefault(rel.page_id, []).append(asset_resp)
                page_id_to_asset_rels.setdefault(rel.page_id, []).append(
                    PagesAssetsRelOverviewResponse.from_dao(rel)
                )

        return [
            cls(
                **PagesOverviewResponse.from_dao(page).model_dump(),
                assets=page_id_to_assets.get(page.id, []),
                page_asset_rels=page_id_to_asset_rels.get(page.id, []),
            )
            for page in pages
        ]


class PageAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/pages/{page_id}/user_message", "page_edit_user_message", ["POST"]
        )
        self.route(
            "/api/pages/{page_id}/photo_slots",
            "page_patch_photo_slots",
            ["PATCH"],
        )

    @enforce_response_model
    async def page_edit_user_message(
        self,
        request: Request,
        page_id: UUID,
        payload: PageEditUserMessageRequest,
    ) -> PagesOverviewResponse:
        async with self.app.new_db_session() as db_session:
            request_context = await self.get_request_context(request)
            page = await self.get_page_assert_owned_by(
                db_session, page_id, request_context.owner_id
            )

            async with safe_commit(db_session):
                updated_page = await DALPages.update_by_id(
                    db_session,
                    page.id,
                    DAOPagesUpdate(user_message=payload.user_message),
                )
            return PagesOverviewResponse.from_dao(updated_page)

    @enforce_response_model
    async def page_patch_photo_slots(
        self,
        request: Request,
        page_id: UUID,
        payload: PatchPhotoSlotsRequest,
    ) -> PagesFullResponse:
        async with self.app.new_db_session() as db_session:
            request_context = await self.get_request_context(request)

            # All mutations + lock happen in one transaction
            async with safe_transaction(db_session, context="patch photo slots"):
                await self.get_page_assert_owned_by(
                    db_session, page_id, request_context.owner_id
                )

                # 1) Lock the page row FOR UPDATE
                async with locked_row_by_id(db_session, DAOPages, page_id) as page:
                    something_changed = False

                    # 2a) Delete any dropped rels
                    existing_asset_rels = await DALPagesAssetsRel.list_all(
                        db_session, filters={"page_id": (FilterOp.EQ, page.id)}
                    )
                    incoming_asset_rels = {
                        slot.assetRelId for slot in payload.slots if slot.assetRelId
                    }
                    asset_rel_deletes = [
                        rel.id
                        for rel in existing_asset_rels
                        if rel.id not in incoming_asset_rels
                    ]
                    if asset_rel_deletes:
                        something_changed = True
                        await DALPagesAssetsRel.delete_many_by_ids(
                            db_session, asset_rel_deletes
                        )

                    # 2b) Create new rels for slots with no assetRelId
                    asset_rel_creates: list[DAOPagesAssetsRelCreate] = []
                    for slot in payload.slots:
                        if slot.assetRelId is None:
                            something_changed = True
                            asset_rel_creates.append(
                                DAOPagesAssetsRelCreate(
                                    page_id=page.id,
                                    asset_id=slot.assetId,
                                    order_index=slot.order,
                                )
                            )
                    if asset_rel_creates:
                        await DALPagesAssetsRel.create_many(
                            db_session, asset_rel_creates
                        )

                    # 2c) Re-order all provided slots in one batch
                    #    (only existing rels; newly created ones already have correct order_index)
                    asset_rel_updates: dict[UUID, DAOPagesAssetsRelUpdate] = {
                        slot.assetRelId: DAOPagesAssetsRelUpdate(order_index=slot.order)
                        for slot in payload.slots
                        if slot.assetRelId is not None
                    }
                    if asset_rel_updates:
                        something_changed = True
                        await DALPagesAssetsRel.update_many_by_ids(
                            db_session, asset_rel_updates
                        )

                    # 2d) Bump the page revision if anything changed
                    if something_changed:
                        page_obj_update = DAOPagesUpdate(
                            revision=page.revision + 1,
                        )
                        if asset_rel_deletes or asset_rel_creates:
                            # Invalidate user_message_alternative_options as assets on this page are now different
                            page_obj_update.user_message_alternative_options_outdated = True
                        await DALPages.update_by_id(
                            db_session, page.id, page_obj_update
                        )

            # 3) Return the fresh, fully-rendered page
            full = await PagesFullResponse.rendered_from_daos(
                [page], db_session, self.app.asset_manager
            )
            return full[0]
