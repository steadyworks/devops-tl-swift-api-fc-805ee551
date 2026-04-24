import logging
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from fastapi import BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALNotifications,
    DALPhotobooks,
    DALPhotobookShare,
    DALUsers,
)
from backend.db.dal.base import (
    FilterOp,
    OrderDirection,
    safe_commit,
    safe_transaction,
)
from backend.db.dal.schemas import (
    DAONotificationsCreate,
    DAOPhotobookShareCreate,
)
from backend.db.data_models import (
    DAOPhotobooks,
    DAOPhotobookShare,
    DAOUsers,
    NotificationType,
    PhotobookStatus,
    ShareRole,
)
from backend.lib.utils.common import none_throws

if TYPE_CHECKING:
    from backend.lib.request.context import RequestContext

from backend.db.data_models.types import AutoCompleteUser
from backend.route_handler.base import RouteHandler, enforce_response_model


class SharePhotobookRequest(BaseModel):
    raw_emails_to_share: list[str]
    invited_user_ids: list[UUID] = []
    custom_message: str = ""
    role: ShareRole = ShareRole.VIEWER


class SharePhotobookResponse(BaseModel):
    already_shared_users: list[AutoCompleteUser]
    already_shared_emails: list[str]


class SharePhotobookAutocompleteResponse(BaseModel):
    users: list[AutoCompleteUser]
    raw_emails: list[str]
    already_shared_users: list[AutoCompleteUser]
    already_shared_emails: list[str]


class SharePhotobookRemoveRequest(BaseModel):
    email: str
    user_id: Optional[UUID] = None


class SharePhotobookRemoveResponse(BaseModel):
    already_shared_users: list[AutoCompleteUser]
    already_shared_emails: list[str]


class SharedData(BaseModel):
    already_shared_users: List[AutoCompleteUser]
    already_shared_emails: List[str]


class ShareAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/share/photobooks/{photobook_id}",
            "share_photobook",
            methods=["POST"],
        )
        self.route(
            "/api/share/get_share_autocomplete_options/{photobook_id}",
            "get_share_autocomplete_options",
            methods=["GET"],
        )
        self.route(
            "/api/share/remove_share/{photobook_id}",
            "remove_share",
            methods=["POST"],
        )

    @classmethod
    async def find_photobook_shares(
        cls,
        db_session: AsyncSession,
        photobook_id: UUID,
    ) -> SharedData:
        current_photobook_shares: list[
            DAOPhotobookShare
        ] = await DALPhotobookShare.list_all(
            db_session,
            filters={"photobook_id": (FilterOp.EQ, photobook_id)},
        )
        current_photobook_emails: list[str] = [
            share.email for share in current_photobook_shares if share.email
        ]
        current_photobook_shared_users = await DALUsers.list_all(
            db_session,
            filters={
                "id": (
                    FilterOp.IN,
                    [
                        share.invited_user_id
                        for share in current_photobook_shares
                        if share.invited_user_id
                    ],
                )
            },
        )
        return SharedData(
            already_shared_users=[
                AutoCompleteUser(
                    email=user.email,
                    username=user.name,
                    user_id=user.id,
                )
                for user in current_photobook_shared_users
                if user.email is not None  # user must have an email
            ],
            already_shared_emails=[
                e
                for e in current_photobook_emails
                if e not in {u.email for u in current_photobook_shared_users}
            ],
        )

    @enforce_response_model
    async def remove_share(
        self,
        photobook_id: UUID,
        request: Request,
        payload: SharePhotobookRemoveRequest,
    ) -> SharePhotobookRemoveResponse:
        request_context: RequestContext = await self.get_request_context(request)

        # User must log in to remove photobook share
        _owner_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            # Validate photobook ownership
            await self.get_photobook_assert_owned_by(
                db_session, photobook_id, request_context.owner_id
            )

            shares: list[DAOPhotobookShare] = []
            # Remove all shares for the photobook
            if payload.user_id:
                # Remove share by user ID
                shares = await DALPhotobookShare.list_all(
                    db_session,
                    filters={
                        "photobook_id": (FilterOp.EQ, photobook_id),
                        "invited_user_id": (FilterOp.EQ, payload.user_id),
                    },
                )
                if len(shares) > 0:
                    await DALPhotobookShare.delete_by_id(db_session, shares[0].id)
            else:
                # Remove share by email
                shares = await DALPhotobookShare.list_all(
                    db_session,
                    filters={
                        "photobook_id": (FilterOp.EQ, photobook_id),
                        "email": (FilterOp.EQ, payload.email),
                    },
                )
                if len(shares) > 0:
                    await DALPhotobookShare.delete_by_id(db_session, shares[0].id)
            # Fetch all shares for the photobook to return
            shared_data: SharedData = await self.find_photobook_shares(
                db_session, photobook_id
            )

            return SharePhotobookRemoveResponse(
                already_shared_emails=shared_data.already_shared_emails,
                already_shared_users=shared_data.already_shared_users,
            )

    @enforce_response_model
    async def get_share_autocomplete_options(
        self,
        photobook_id: UUID,
        request: Request,
    ) -> SharePhotobookAutocompleteResponse:
        """
        Fetch the history of everyone the current user has shared photobooks with.
        """
        request_context: RequestContext = await self.get_request_context(request)
        async with self.app.new_db_session() as db_session:
            # fetch everything the current user has shared for auto complete
            photobooks: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                {
                    "owner_id": (FilterOp.EQ, request_context.owner_id),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
                order_by=[("updated_at", OrderDirection.DESC)],
            )
            current_user_all_photobook_shares: list[
                DAOPhotobookShare
            ] = await DALPhotobookShare.list_all(
                db_session,
                filters={
                    "photobook_id": (
                        FilterOp.IN,
                        [pb.id for pb in photobooks],
                    )
                },
            )
            raw_emails: list[str] = [
                share.email
                for share in current_user_all_photobook_shares
                if share.email
            ]
            ever_shared_users: list[DAOUsers] = await DALUsers.list_all(
                db_session,
                filters={
                    "id": (
                        FilterOp.IN,
                        [
                            share.invited_user_id
                            for share in current_user_all_photobook_shares
                            if share.invited_user_id
                        ],
                    )
                },
            )
            # Return current photobook shares for UI Rendering
            # of "People with access"
            shared_data: SharedData = await self.find_photobook_shares(
                db_session, photobook_id
            )

            return SharePhotobookAutocompleteResponse(
                users=[
                    AutoCompleteUser(
                        email=user.email,
                        username=user.name,
                        user_id=user.id,
                    )
                    for user in ever_shared_users
                    if user.email is not None  # user must have an email
                ],
                raw_emails=[
                    e
                    for e in raw_emails
                    if e not in {u.email for u in ever_shared_users}
                ],
                already_shared_users=shared_data.already_shared_users,
                already_shared_emails=shared_data.already_shared_emails,
            )

    async def _create_share_notifications(
        self,
        photobook_id: UUID,
        owner_user_id: UUID,
        invited_user_ids: set[UUID],
        custom_message: str,
    ) -> None:
        """
        Background task to create notifications for shared users.
        """
        try:
            async with self.app.new_db_session() as db_session:
                owner: DAOUsers = none_throws(
                    await DALUsers.get_by_id(db_session, owner_user_id)
                )
                photobook: DAOPhotobooks = none_throws(
                    await DALPhotobooks.get_by_id(db_session, photobook_id)
                )

                title = f"{owner.name or 'Someone'} shared {photobook.title} with you"
                body = custom_message or (photobook.title or "A photobook")
                cta_url = (
                    f"/photobook/{photobook_id}"  # adjust if you have a canonical route
                )

                async with safe_commit(db_session):
                    for invited_user_id in invited_user_ids:
                        await DALNotifications.create(
                            db_session,
                            DAONotificationsCreate(
                                recipient_id=invited_user_id,
                                actor_id=owner_user_id,
                                type=NotificationType.SHARE,
                                title=title,
                                body=body,
                                cta_url=cta_url,
                                payload={
                                    "photobook_id": str(photobook_id),
                                },
                                group_key=f"share:{photobook_id}",
                            ),
                        )
        except Exception as e:
            logging.error(f"Error creating share notifications: {e}")

    @enforce_response_model
    async def share_photobook(
        self,
        photobook_id: UUID,
        request: Request,
        payload: SharePhotobookRequest,
        background_tasks: BackgroundTasks,
    ) -> SharePhotobookResponse:
        request_context: RequestContext = await self.get_request_context(request)

        # User must log in to share photobook
        owner_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            async with safe_transaction(
                db_session, context="share photobook", raise_on_fail=True
            ):
                # Validate photobook ownership
                await self.get_photobook_assert_owned_by(
                    db_session,
                    photobook_id,
                    request_context.owner_id,
                )

                # let's process emails by checking if they belong to existing users
                existing_users: list[DAOUsers] = await DALUsers.list_all(
                    db_session,
                    filters={"email": (FilterOp.IN, payload.raw_emails_to_share)},
                )
                raw_emails = set(payload.raw_emails_to_share) - set(
                    [user.email for user in existing_users]
                )
                for email in raw_emails:
                    await DALPhotobookShare.create(
                        db_session,
                        DAOPhotobookShareCreate(
                            photobook_id=photobook_id,
                            email=email,
                            invited_user_id=None,  # Assuming email sharing
                            role=payload.role,
                            custom_message=payload.custom_message,
                        ),
                    )
                invited_user_ids = set(
                    payload.invited_user_ids + [u.id for u in existing_users]
                )
                for user_id in invited_user_ids:
                    await DALPhotobookShare.create(
                        db_session,
                        DAOPhotobookShareCreate(
                            photobook_id=photobook_id,
                            email=None,  # Assuming user ID sharing
                            invited_user_id=user_id,
                            role=payload.role,
                            custom_message=payload.custom_message,
                        ),
                    )
                background_tasks.add_task(
                    self._create_share_notifications,
                    photobook_id,
                    owner_user_id,
                    invited_user_ids,
                    payload.custom_message,
                )
            # current photobook shares
            shared_data: SharedData = await self.find_photobook_shares(
                db_session, photobook_id
            )

            return SharePhotobookResponse(
                already_shared_users=shared_data.already_shared_users,
                already_shared_emails=shared_data.already_shared_emails,
            )
