import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import List, Optional, Self
from uuid import UUID

from fastapi import (
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
)
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALAssets,
    DALPages,
    DALPhotobookComments,
    DALPhotobooks,
    DALPhotobooksAssetsRel,
    DALPhotobookSettings,
    DALUsers,
    DAOPagesCreate,
    DAOPagesUpdate,
    DAOPhotobookCommentsCreate,
    DAOPhotobookCommentsUpdate,
    DAOPhotobooksAssetsRelCreate,
    DAOPhotobooksCreate,
    DAOPhotobookSettingsCreate,
    DAOPhotobooksUpdate,
    FilterOp,
    OrderDirection,
    locked_row_by_id,
    safe_commit,
    safe_transaction,
)
from backend.db.dal.schemas import DAOPhotobookSettingsUpdate
from backend.db.data_models import (
    CommentStatus,
    DAOPages,
    DAOPhotobookComments,
    DAOPhotobooks,
    DAOPhotobookSettings,
    DAOUsers,
    FontStyle,
    NotificationStatus,
    PhotobookStatus,
    UserProvidedOccasion,
)
from backend.db.externals import (
    AssetsOverviewResponse,
    PagesOverviewResponse,
    PhotobooksOverviewResponse,
)
from backend.lib.asset_manager.base import AssetManager
from backend.lib.request.context import RequestContext
from backend.lib.utils.common import utcnow
from backend.lib.websocket.codec import WebSocketCodec
from backend.lib.websocket.registry import WebSocketRegistry
from backend.lib.websocket.types import (
    AssetUploadStatusMessage,
    PhotobookStatusErrorMessage,
    PhotobookStatusErrorPayload,
    PhotobookStatusSubscribeMessage,
    PhotobookStatusUpdateMessage,
    PhotobookStatusUpdatePayload,
    ServerToClientWebSocketEventType,
)
from backend.route_handler.base import RouteHandler
from backend.worker.job_processor.types import (
    JobType,
    PhotobookGenerationInputPayload,
)

from .base import enforce_response_model, unauthenticated_route
from .page import PagesFullResponse


class UploadedFileInfo(BaseModel):
    filename: str
    storage_key: str


class FailedUploadInfo(BaseModel):
    filename: str
    error: str


class NewPhotobookRequest(BaseModel):
    user_provided_occasion: UserProvidedOccasion
    user_gift_recipients: Optional[str] = None
    user_provided_context: Optional[str] = None
    asset_ids: list[UUID]


class NewPhotobookResponse(BaseModel):
    photobook_id: UUID


class PhotobookPatchRequest(BaseModel):
    title: Optional[str] = None
    background_color_palette: Optional[str] = None
    theme: Optional[str] = None
    suggested_overall_gift_message: Optional[str] = None


class PhotobookSettingsRequest(BaseModel):
    photobook_id: UUID


class PhotobookEditSettingsRequest(BaseModel):
    photobook_id: UUID
    is_comment_enabled: bool
    is_allow_download_all_images_enabled: bool
    is_tipping_enabled: bool


class PhotobooksEditSettingsResponse(BaseModel):
    photobook_id: UUID
    is_comment_enabled: bool
    is_allow_download_all_images_enabled: bool
    is_tipping_enabled: bool


class PhotobookStyleRequest(BaseModel):
    photobook_id: UUID


class PhotobookEditStyleRequest(BaseModel):
    photobook_id: UUID
    main_style: Optional[str] = None
    font: Optional[FontStyle] = None


class PhotobookEditStyleResponse(BaseModel):
    photobook_id: UUID
    main_style: Optional[str] = None
    font: Optional[FontStyle] = None


class PatchPageSlotsItem(BaseModel):
    page_id: UUID
    order: int


class PatchPageSlotsRequest(BaseModel):
    slots: list[PatchPageSlotsItem]

    @field_validator("slots")
    @classmethod
    def validate_basic(
        cls, slots: list[PatchPageSlotsItem]
    ) -> list[PatchPageSlotsItem]:
        if not slots:
            raise ValueError("slots must not be empty")
        # local (shape) checks; we’ll re-validate against DB later
        orders = [s.order for s in slots]
        if len(set(orders)) != len(orders):
            raise ValueError("Duplicate order values in slots.")
        if min(orders) != 0 or max(orders) != len(orders) - 1:
            raise ValueError("Orders must be contiguous 0..N-1.")
        return slots


class PatchPageSlotsResponse(BaseModel):
    photobook_id: UUID
    pages: list[PagesOverviewResponse]


class CommentResponse(BaseModel):
    comment_body: str
    comment_id: UUID
    created_at: Optional[datetime]
    user_id: Optional[UUID]
    user_name: Optional[str]
    user_profile_image_url: Optional[str]

    @classmethod
    def from_raw_comment(
        cls,
        comment: DAOPhotobookComments,
        users: List[DAOUsers],
    ) -> Self:
        user = next((u for u in users if u.id == comment.user_id), None)
        return cls(
            comment_body=comment.body,
            comment_id=comment.id,
            created_at=comment.created_at,
            user_id=comment.user_id,
            user_name=user.name if user else None,
            user_profile_image_url=None,  # TODO: implement user profile image URL retrieval
        )


class PhotobooksFullResponse(PhotobooksOverviewResponse):
    pages: list[PagesFullResponse]
    comments: list[CommentResponse]
    associated_assets: list[AssetsOverviewResponse]

    @classmethod
    async def rendered_from_dao(
        cls: type[Self],
        dao: DAOPhotobooks,
        db_session: AsyncSession,
        asset_manager: AssetManager,
    ) -> Self:
        resp: PhotobooksOverviewResponse = (
            await PhotobooksOverviewResponse.rendered_from_daos(
                [dao],
                db_session,
                asset_manager,
            )
        )[0]
        pages: list[DAOPages] = await DALPages.list_all(
            db_session,
            {"photobook_id": (FilterOp.EQ, dao.id)},
            order_by=[("page_number", OrderDirection.ASC)],
        )
        pages_response_full: list[
            PagesFullResponse
        ] = await PagesFullResponse.rendered_from_daos(pages, db_session, asset_manager)
        comments: list[DAOPhotobookComments] = await DALPhotobookComments.list_all(
            db_session,
            filters={
                "photobook_id": (FilterOp.EQ, dao.id),
                "status": (FilterOp.EQ, CommentStatus.VISIBLE),
            },
            order_by=[("created_at", OrderDirection.DESC)],
        )
        users: List[DAOUsers] = await DALUsers.list_all(
            db_session,
            filters={"id": (FilterOp.IN, list(set(c.user_id for c in comments)))},
        )
        comments_response: list[CommentResponse] = [
            CommentResponse.from_raw_comment(c, users) for c in comments
        ]
        associated_asset_rel_daos = await DALPhotobooksAssetsRel.list_all(
            db_session, {"photobook_id": (FilterOp.EQ, dao.id)}
        )
        associated_asset_daos = await DALAssets.list_all(
            db_session,
            {
                "id": (
                    FilterOp.IN,
                    list(set(rel.asset_id for rel in associated_asset_rel_daos)),
                )
            },
        )
        associated_asset_resps = await AssetsOverviewResponse.rendered_from_daos(
            associated_asset_daos,
            asset_manager,
        )

        return cls(
            **resp.model_dump(),
            pages=pages_response_full,
            comments=comments_response,
            associated_assets=associated_asset_resps,
        )


class EditPageRequest(BaseModel):
    page_id: UUID
    new_user_message: str


class PhotobookEditPagesRequest(BaseModel):
    edits: list[EditPageRequest]


class PhotobookDeleteResponse(BaseModel):
    success: bool
    error_message: Optional[str] = None


class CreateCommentRequest(BaseModel):
    body: str


class CreateCommentResponse(BaseModel):
    comment: CommentResponse


class EditCommentRequest(BaseModel):
    body: str


class EditCommentResponse(BaseModel):
    comment: CommentResponse


class PhotobookAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route("/api/photobook/new", "photobook_new", ["POST"])
        self.route("/api/photobook/{photobook_id}", "get_photobook_by_id", ["GET"])
        self.route(
            "/api/photobook/{photobook_id}",
            "photobook_patch",
            ["PATCH"],
        )
        self.route(
            "/api/photobook/{photobook_id}/edit_pages",
            "photobook_edit_pages",
            ["POST"],
        )
        self.route(
            "/api/photobook/{photobook_id}/delete",
            "photobook_delete",
            ["POST"],
        )
        self.route(
            "/api/photobook/{photobook_id}/comment",
            "photobook_create_comment",
            ["POST"],
        )
        self.route(
            "/api/photobook/{photobook_id}/comment/{comment_id}/edit",
            "photobook_edit_comment",
            ["POST"],
        )
        self.route(
            "/api/photobook_settings/{photobook_id}/edit_style",
            "photobook_edit_style",
            ["POST"],
        )
        self.route(
            "/api/photobook_settings/{photobook_id}/edit_settings",
            "photobook_edit_settings",
            ["POST"],
        )
        self.route(
            "/api/photobook_settings/{photobook_id}/style",
            "get_photobook_style_by_id",
            ["GET"],
        )
        self.route(
            "/api/photobook_settings/{photobook_id}/settings",
            "get_photobook_settings_by_id",
            ["GET"],
        )
        self.route(
            "/api/photobook/{photobook_id}/page_slots",
            "photobook_patch_page_slots",
            ["PATCH"],
        )
        self.route(
            "/api/photobook/{photobook_id}/new_page",
            "photobook_new_page",
            ["POST"],
        )

        # Websockets
        self.websocket_route("/api/ws/photobook/status", "photobook_status_ws")

    @enforce_response_model
    async def photobook_new(
        self,
        request: Request,
        payload: NewPhotobookRequest,
    ) -> NewPhotobookResponse:
        request_context: RequestContext = await self.get_request_context(request)

        # Persist metadata with new photobook DB entry
        async with self.app.new_db_session() as db_session:
            async with safe_transaction(
                db_session,
                context="photobook creation DB write",
                raise_on_fail=True,
            ):
                photobook: DAOPhotobooks = await DALPhotobooks.create(
                    db_session,
                    DAOPhotobooksCreate(
                        owner_id=request_context.owner_id,
                        title=f"New Photobook {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        caption=None,
                        theme=None,
                        status=PhotobookStatus.PENDING,
                        user_provided_occasion=payload.user_provided_occasion,
                        user_provided_occasion_custom_details=None,
                        user_provided_context=payload.user_provided_context,
                        user_gift_recipient=payload.user_gift_recipients,
                        thumbnail_asset_id=None,
                        deleted_at=None,
                        status_last_edited_by=None,
                        background_color_palette="default",
                    ),
                )
                await DALPhotobookSettings.create(
                    db_session,
                    DAOPhotobookSettingsCreate(
                        photobook_id=photobook.id,
                        main_style=None,
                        font=FontStyle.UNSPECIFIED,
                        is_comment_enabled=False,
                        is_allow_download_all_images_enabled=False,
                        is_tipping_enabled=False,
                    ),
                )
                await DALPhotobooksAssetsRel.create_many(
                    db_session,
                    [
                        DAOPhotobooksAssetsRelCreate(
                            asset_id=asset_id,
                            photobook_id=photobook.id,
                        )
                        for asset_id in payload.asset_ids
                    ],
                )

            # Enqueue photobook generation job
            await self.app.remote_job_manager_cpu_bound.enqueue(
                JobType.REMOTE_PHOTOBOOK_GENERATION,
                job_payload=PhotobookGenerationInputPayload(
                    owner_id=request_context.owner_id,
                    user_id=None,
                    originating_photobook_id=photobook.id,
                    asset_ids=payload.asset_ids,
                ),
                max_retries=2,
                db_session=db_session,
            )

        return NewPhotobookResponse(
            photobook_id=photobook.id,
        )

    @unauthenticated_route
    @enforce_response_model
    async def get_photobook_by_id(
        self,
        photobook_id: UUID,
    ) -> PhotobooksFullResponse:
        async with self.app.new_db_session() as db_session:
            # Step 1: Fetch photobook
            photobook: DAOPhotobooks | None = await DALPhotobooks.get_by_id(
                db_session, photobook_id
            )
            if photobook is None:
                raise HTTPException(status_code=404, detail="Photobook not found")
            return await PhotobooksFullResponse.rendered_from_dao(
                photobook, db_session, self.app.asset_manager
            )

    @enforce_response_model
    async def get_photobook_style_by_id(
        self,
        photobook_id: UUID,
    ) -> PhotobookEditStyleResponse:
        async with self.app.new_db_session() as db_session:
            photobook_settings: DAOPhotobookSettings = (
                await self._get_photobook_setting_by_photobook_id(
                    db_session, photobook_id
                )
            )

            return PhotobookEditStyleResponse(
                photobook_id=photobook_id,
                main_style=photobook_settings.main_style,
                font=photobook_settings.font,
            )

    @enforce_response_model
    async def get_photobook_settings_by_id(
        self,
        photobook_id: UUID,
    ) -> PhotobooksEditSettingsResponse:
        async with self.app.new_db_session() as db_session:
            photobook_settings: DAOPhotobookSettings = (
                await self._get_photobook_setting_by_photobook_id(
                    db_session, photobook_id
                )
            )

            return PhotobooksEditSettingsResponse(
                photobook_id=photobook_id,
                is_comment_enabled=photobook_settings.is_comment_enabled,
                is_allow_download_all_images_enabled=photobook_settings.is_allow_download_all_images_enabled,
                is_tipping_enabled=photobook_settings.is_tipping_enabled,
            )

    @enforce_response_model
    async def photobook_patch(
        self, photobook_id: UUID, payload: PhotobookPatchRequest, request: Request
    ) -> PhotobooksOverviewResponse:
        async with self.app.new_db_session() as db_session:
            request_context = await self.get_request_context(request)
            await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.owner_id
            )
            async with safe_commit(db_session):
                update_data = payload.model_dump(exclude_none=True)
                photobook: DAOPhotobooks = await DALPhotobooks.update_by_id(
                    db_session,
                    photobook_id,
                    DAOPhotobooksUpdate(**update_data),
                )
            return (
                await PhotobooksOverviewResponse.rendered_from_daos(
                    [photobook], db_session, self.app.asset_manager
                )
            )[0]

    @enforce_response_model
    async def photobook_edit_style(
        self, photobook_id: UUID, payload: PhotobookEditStyleRequest
    ) -> PhotobookEditStyleResponse:
        async with self.app.new_db_session() as db_session:
            photobook_settings: DAOPhotobookSettings = (
                await self._get_photobook_setting_by_photobook_id(
                    db_session, photobook_id
                )
            )
            async with safe_commit(db_session):
                updated_photobook_settings: DAOPhotobookSettings = (
                    await DALPhotobookSettings.update_by_id(
                        db_session,
                        photobook_settings.id,
                        DAOPhotobookSettingsUpdate(
                            photobook_id=photobook_id,
                            main_style=payload.main_style,
                            font=payload.font,
                            updated_at=utcnow(),
                        ),
                    )
                )

            return PhotobookEditStyleResponse(
                photobook_id=photobook_id,
                main_style=updated_photobook_settings.main_style,
                font=updated_photobook_settings.font,
            )

    @enforce_response_model
    async def photobook_edit_settings(
        self, photobook_id: UUID, payload: PhotobookEditSettingsRequest
    ) -> PhotobooksEditSettingsResponse:
        async with self.app.new_db_session() as db_session:
            photobook_settings: DAOPhotobookSettings = (
                await self._get_photobook_setting_by_photobook_id(
                    db_session, photobook_id
                )
            )
            async with safe_commit(db_session):
                updated_photobook_settings: DAOPhotobookSettings = await DALPhotobookSettings.update_by_id(
                    db_session,
                    photobook_settings.id,
                    DAOPhotobookSettingsUpdate(
                        photobook_id=photobook_id,
                        is_comment_enabled=payload.is_comment_enabled,
                        is_allow_download_all_images_enabled=payload.is_allow_download_all_images_enabled,
                        is_tipping_enabled=payload.is_tipping_enabled,
                        updated_at=utcnow(),
                    ),
                )

            return PhotobooksEditSettingsResponse(
                photobook_id=photobook_id,
                is_comment_enabled=updated_photobook_settings.is_comment_enabled,
                is_allow_download_all_images_enabled=updated_photobook_settings.is_allow_download_all_images_enabled,
                is_tipping_enabled=updated_photobook_settings.is_tipping_enabled,
            )

    @enforce_response_model
    async def photobook_edit_pages(
        self,
        photobook_id: UUID,
        payload: PhotobookEditPagesRequest,
        request: Request,
    ) -> PhotobooksFullResponse:
        request_context = await self.get_request_context(request)
        async with self.app.new_db_session() as db_session:
            # 1. Validate photobook exists
            photobook = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.owner_id
            )
            # 2. Batch apply page updates
            async with safe_commit(db_session):
                update_map: dict[UUID, DAOPagesUpdate] = {
                    edit.page_id: DAOPagesUpdate(user_message=edit.new_user_message)
                    for edit in payload.edits
                }
                await DALPages.update_many_by_ids(db_session, update_map)

            # 3. Return updated photobook and its pages
            return await PhotobooksFullResponse.rendered_from_dao(
                photobook, db_session, self.app.asset_manager
            )

    @enforce_response_model
    async def photobook_delete(
        self,
        photobook_id: UUID,
        request: Request,
    ) -> PhotobookDeleteResponse:
        request_context = await self.get_request_context(request)
        async with self.app.new_db_session() as db_session:
            # 1. Validate photobook exists
            photobook = await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.owner_id
            )

            if (
                photobook.status == PhotobookStatus.DELETED
                or photobook.status == PhotobookStatus.PERMANENTLY_DELETED
            ):
                return PhotobookDeleteResponse(
                    success=False, error_message="Photobook already deleted"
                )

            async with safe_commit(db_session):
                await DALPhotobooks.update_by_id(
                    db_session,
                    photobook_id,
                    DAOPhotobooksUpdate(
                        deleted_at=utcnow(), status=PhotobookStatus.DELETED
                    ),
                )

            return PhotobookDeleteResponse(success=True)

    @enforce_response_model
    async def photobook_create_comment(
        self,
        request: Request,
        photobook_id: UUID,
        payload: CreateCommentRequest,
    ) -> CreateCommentResponse:
        request_context: RequestContext = await self.get_request_context(request)

        # User must be logged in
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            async with safe_commit(db_session):
                comment: DAOPhotobookComments = await DALPhotobookComments.create(
                    db_session,
                    DAOPhotobookCommentsCreate(
                        photobook_id=photobook_id,
                        user_id=logged_in_user_id,
                        body=payload.body,
                        status=CommentStatus.VISIBLE,
                        notification_status=NotificationStatus.PENDING,
                    ),
                )
                user: DAOUsers | None = await DALUsers.get_by_id(
                    db_session, logged_in_user_id
                )

                if user is None:
                    raise HTTPException(status_code=404, detail="User not found")

                return CreateCommentResponse(
                    comment=CommentResponse.from_raw_comment(comment, [user])
                )

    @enforce_response_model
    async def photobook_edit_comment(
        self,
        request: Request,
        photobook_id: UUID,
        comment_id: UUID,
        payload: EditCommentRequest,
    ) -> EditCommentResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            comment: DAOPhotobookComments | None = await DALPhotobookComments.get_by_id(
                db_session, comment_id
            )
            if comment is None or comment.photobook_id != photobook_id:
                raise HTTPException(status_code=404, detail="Comment not found")

            if comment.user_id != logged_in_user_id:
                raise HTTPException(
                    status_code=403,
                    detail="You can only edit your own comment",
                )

            async with safe_commit(db_session):
                updated_comment: DAOPhotobookComments = (
                    await DALPhotobookComments.update_by_id(
                        db_session,
                        comment_id,
                        DAOPhotobookCommentsUpdate(
                            body=payload.body,
                            last_updated_by=logged_in_user_id,
                        ),
                    )
                )
                user: DAOUsers | None = await DALUsers.get_by_id(
                    db_session, logged_in_user_id
                )

                if user is None:
                    raise HTTPException(status_code=404, detail="User not found")

                return EditCommentResponse(
                    comment=CommentResponse.from_raw_comment(updated_comment, [user])
                )

    async def _get_photobook_setting_by_photobook_id(
        self, db_session: AsyncSession, photobook_id: UUID
    ) -> DAOPhotobookSettings:
        settings: List[DAOPhotobookSettings] = await DALPhotobookSettings.list_all(
            db_session,
            filters={"photobook_id": (FilterOp.EQ, photobook_id)},
        )
        if not settings:
            raise HTTPException(status_code=404, detail="Photobook settings not found")
        if len(settings) > 1:
            raise HTTPException(
                status_code=500,
                detail="Multiple photobook settings found for a single photobook",
            )
        return settings[0]

    @enforce_response_model
    async def photobook_patch_page_slots(
        self,
        request: Request,
        photobook_id: UUID,
        payload: PatchPageSlotsRequest,
    ) -> PatchPageSlotsResponse:
        async with self.app.new_db_session() as db_session:
            request_context = await self.get_request_context(request)

            async with safe_transaction(
                db_session, context="patch photobook page slots"
            ):
                # 0) Ownership
                await self.get_photobook_assert_owned_by(
                    db_session, photobook_id, request_context.owner_id
                )

                # 1) Lock the photobook row to serialize concurrent structure ops
                async with locked_row_by_id(
                    db_session, DAOPhotobooks, photobook_id
                ) as _book:
                    # 2) Load & (optionally) lock current pages
                    pages: list[DAOPages] = await DALPages.list_all(
                        db_session,
                        filters={"photobook_id": (FilterOp.EQ, photobook_id)},
                        order_by=[("page_number", OrderDirection.ASC)],
                    )

                    # 3) Derive sets
                    existing_ids = {p.id for p in pages}
                    incoming_ids = {s.page_id for s in payload.slots}

                    # Pages to delete (present in DB, missing in payload)
                    delete_ids = list(existing_ids - incoming_ids)

                    # Reorders/updates (payload with page_id!=None)
                    updates_spec = [s for s in payload.slots]

                    # 4) Compute and apply mutations
                    _something_changed = False

                    # 5a) Deletes
                    if delete_ids:
                        _something_changed = True
                        await DALPages.delete_many_by_ids(db_session, delete_ids)

                    # Rebuild working index after deletes/creates
                    pages_by_id = {p.id: p for p in pages if p.id not in delete_ids}

                    # 5b) Reorders — minimal updates for survivors
                    # Map payload order by id (only for existing)
                    desired_order_by_id = {
                        s.page_id: s.order for s in updates_spec
                    }  # id->order
                    # Also include the newly-created ones (we already set their page_number above)
                    # Now compute updates for survivors where order changed
                    updates: dict[UUID, DAOPagesUpdate] = {}
                    for pid, page in pages_by_id.items():
                        desired = desired_order_by_id.get(pid)
                        if desired is None:
                            # Not in updates_spec ⇒ either newly created (already set) or deleted
                            continue
                        if page.page_number != desired:
                            updates[pid] = DAOPagesUpdate(page_number=desired)

                    if updates:
                        _something_changed = True
                        await DALPages.update_many_by_ids(db_session, updates)

            # 6) Return fresh, fully ordered list
            updated_pages = await DALPages.list_all(
                db_session,
                filters={"photobook_id": (FilterOp.EQ, photobook_id)},
                order_by=[("page_number", OrderDirection.ASC)],
            )
            return PatchPageSlotsResponse(
                photobook_id=photobook_id,
                pages=[PagesOverviewResponse.from_dao(p) for p in updated_pages],
            )

    @enforce_response_model
    async def photobook_new_page(
        self,
        request: Request,
        photobook_id: UUID,
    ) -> PagesFullResponse:
        """
        Create a new page at the end of the photobook and return its overview.
        """
        request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
            async with safe_transaction(
                db_session,
                context="create new photobook page",
                raise_on_fail=True,
            ):
                # 0) Ownership
                await self.get_photobook_assert_owned_by(
                    db_session, photobook_id, request_context.owner_id
                )

                # 1) Lock the photobook row to serialize concurrent page structure writes
                async with locked_row_by_id(
                    db_session, DAOPhotobooks, photobook_id
                ) as _book:
                    # 2) Determine next page_number (append)
                    highest_page: list[DAOPages] = await DALPages.list_all(
                        db_session,
                        filters={"photobook_id": (FilterOp.EQ, photobook_id)},
                        order_by=[("page_number", OrderDirection.DESC)],
                        limit=1,
                    )
                    next_page_number = (
                        (highest_page[0].page_number + 1) if highest_page else 0
                    )

                    # 3) Create the new page
                    new_page: DAOPages = await DALPages.create(
                        db_session,
                        DAOPagesCreate(
                            photobook_id=photobook_id,
                            page_number=next_page_number,
                            revision=1,
                            user_message_alternative_options_outdated=True,
                            user_message="Enter edit mode to add photos and edit this message.",
                        ),
                    )

            # 4) Return overview response
            resps = await PagesFullResponse.rendered_from_daos(
                [new_page], db_session, self.app.asset_manager
            )
            return resps[0]

    async def photobook_status_ws(self, websocket: WebSocket) -> None:
        # --- Auth (same as upload_status_ws) ---
        async with self.app.new_db_session() as db_session:
            try:
                request_context = await RequestContext.from_websocket(
                    websocket, db_session
                )
                owner_id = request_context.owner_id
            except WebSocketException as e:
                await websocket.close(code=e.code)
                return

        await websocket.accept()
        await WebSocketRegistry.register(owner_id, websocket)
        logging.debug(f"[WS] Photobook status client connected owner_id={owner_id}")

        codec = WebSocketCodec(websocket)
        poll_task: asyncio.Task[None] | None = None

        try:
            async for msg in codec.aiter_recv(
                log_prefix=f"[WS photobook owner_id={owner_id}]",
                keepalive=True,  # ignore malformed frames; keep the socket up
            ):
                try:
                    match msg:
                        case PhotobookStatusSubscribeMessage(payload=payload):
                            # Cancel any existing poller
                            if poll_task and not poll_task.done():
                                poll_task.cancel()
                                with suppress(Exception):
                                    await poll_task
                                poll_task = None

                            # Start poller that streams updates over this websocket
                            poll_task = asyncio.create_task(
                                self._poll_and_stream_photobook_status(
                                    codec, owner_id, payload.photobook_id
                                )
                            )

                        # Ignore other events on this endpoint (keep connection open)
                        case AssetUploadStatusMessage():
                            logging.debug(
                                f"[WS photobook owner_id={owner_id}] "
                                f"Ignoring ASSET_UPLOAD_STATUS_UPDATE on status socket"
                            )

                        case _:
                            logging.warning(
                                f"[WS photobook owner_id={owner_id}] Unknown event: "
                                f"{getattr(msg, 'event', None)}"
                            )

                except Exception as e:
                    logging.warning(f"[WS photobook] handler error: {e}")
                    continue

        except WebSocketDisconnect:
            logging.info(f"[WS] Photobook WS disconnected owner_id={owner_id}")
        finally:
            if poll_task and not poll_task.done():
                poll_task.cancel()
                with suppress(Exception):
                    await poll_task
            await WebSocketRegistry.unregister(owner_id, websocket)

    async def _poll_and_stream_photobook_status(
        self,
        codec: WebSocketCodec,
        owner_id: UUID,
        photobook_id: UUID,
    ) -> None:
        """
        Poll DB periodically and push status changes to the client.
        Stops when a terminal status is reached or connection drops.
        """
        last_status: PhotobookStatus | None = None
        interval = 0.5

        while True:
            # Revalidate each tick with a short-lived session
            async with self.app.new_db_session() as db_session:
                pb = await DALPhotobooks.get_by_id(db_session, photobook_id)

            if pb is None:
                await self._send_pb_error(codec, photobook_id, "photobook not found")
                return
            if pb.owner_id != owner_id:
                await self._send_pb_error(codec, photobook_id, "forbidden")
                return

            pb_status = pb.status

            # Only send when changed (including the first tick)
            if pb_status != last_status:
                last_status = pb_status
                try:
                    await codec.send(
                        PhotobookStatusUpdateMessage(
                            event=ServerToClientWebSocketEventType.PHOTOBOOK_STATUS_UPDATE,
                            payload=PhotobookStatusUpdatePayload(
                                photobook_id=photobook_id,
                                status=pb_status,
                            ),
                        )
                    )
                except Exception as e:
                    logging.info(f"[WS] Photobook send failed; stopping: {e}")
                    return

            # Stop when terminal
            if pb_status != PhotobookStatus.PENDING:
                return

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

    async def _send_pb_error(
        self,
        codec: WebSocketCodec,
        photobook_id: UUID | None,
        message: str,
    ) -> None:
        try:
            await codec.send(
                PhotobookStatusErrorMessage(
                    event=ServerToClientWebSocketEventType.PHOTOBOOK_STATUS_ERROR,
                    payload=PhotobookStatusErrorPayload(
                        photobook_id=photobook_id,
                        message=message,
                    ),
                )
            )
        except Exception:
            pass
