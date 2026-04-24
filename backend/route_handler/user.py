import logging
from typing import TYPE_CHECKING, Optional, Self
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from backend.db.dal import (
    DALNotifications,
    DALOwnerIdentities,
    DALPhotobookBookmarks,
    DALPhotobooks,
    DALPhotobookShare,
    DALUsers,
    DAOPhotobookBookmarksCreate,
    DAOUsers,
    FilterOp,
    OrderDirection,
    safe_commit,
)
from backend.db.data_models import (
    DAONotifications,
    DAOPhotobookBookmarks,
    DAOPhotobooks,
    IdentityKind,
    PhotobookStatus,
)
from backend.db.externals import (
    PhotobookBookmarksOverviewResponse,
    PhotobooksOverviewResponse,
)
from backend.lib.utils.common import none_throws
from backend.route_handler.base import RouteHandler

from .base import enforce_response_model, unauthenticated_route

if TYPE_CHECKING:
    from backend.lib.request.context import RequestContext


class UserBookmarkPhotobookInputPayload(BaseModel):
    photobook_id: UUID
    source_analytics: Optional[str] = None


class UserGetPhotobooksResponse(BaseModel):
    photobooks: list[PhotobooksOverviewResponse]


class UserGetSharedWithMePhotobooksResponse(BaseModel):
    photobooks: list[PhotobooksOverviewResponse]


class UserBookmarkPhotobookDeleteResponse(BaseModel):
    success: bool
    error_message: Optional[str] = None


class NotificationsOverviewResponse(BaseModel):
    id: UUID
    type: str
    created_at: str
    is_seen: bool
    title: Optional[str]
    body: Optional[str]
    group_key: Optional[str] = None
    cta_url: Optional[str] = None

    @classmethod
    async def rendered_from_daos(
        cls,
        daos: list[DAONotifications],
        # db_session: AsyncSession,
    ) -> list[Self]:
        return [
            cls(
                id=dao.id,
                type=dao.type,
                created_at=dao.created_at.isoformat(),
                is_seen=dao.seen_at is not None,
                title=dao.title,
                body=dao.body,
                group_key=dao.group_key,
                cta_url=dao.cta_url,
            )
            for dao in daos
        ]


class UserDashboardResponse(BaseModel):
    username: Optional[str]
    bmc_link: Optional[str]
    notifications: list[NotificationsOverviewResponse]


class UserDashboardEditRequest(BaseModel):
    username: str
    bmc_link: Optional[str] = None


class UserEditUsernameResponse(BaseModel):
    success: bool
    error_message: Optional[str] = None
    username: Optional[str] = None
    bmc_link: Optional[str] = None


class UserGetBMCLink(BaseModel):
    # profile image later
    user_id: UUID
    username: Optional[str]
    bmc_link: Optional[str]


class UserAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route(
            "/api/user/photobooks",
            "user_get_photobooks",
            methods=["GET"],
        )
        self.route(
            "/api/user/photobooks/bookmarks",
            "user_get_bookmarked_photobooks",
            methods=["GET"],
        )
        self.route(
            "/api/user/photobooks/bookmark_new",
            "user_photobook_bookmark_new",
            methods=["POST"],
        )
        self.route(
            "/api/user/photobooks/bookmark_remove/{photobook_id}",
            "user_photobook_bookmark_remove",
            methods=["DELETE"],
        )
        self.route(
            "/api/user/shared_with_me",
            "get_shared_with_me_photobooks",
            ["GET"],
        )
        self.route(
            "/api/user/dashboard",
            "get_dashboard",
            ["GET"],
        )
        self.route(
            "/api/user/edit",
            "user_edit_username",
            ["POST"],
        )
        self.route(
            "/api/user/bmc_link/{owner_id}",
            "get_user_bmc_link",
            methods=["GET"],
        )

    @enforce_response_model
    async def user_get_photobooks(
        self,
        request: Request,
    ) -> UserGetPhotobooksResponse:
        request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
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
            resp = UserGetPhotobooksResponse(
                photobooks=await PhotobooksOverviewResponse.rendered_from_daos(
                    photobooks, db_session, self.app.asset_manager
                )
            )
            return resp

    @enforce_response_model
    async def user_get_bookmarked_photobooks(
        self,
        request: Request,
    ) -> UserGetPhotobooksResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            photobook_bookmarks: list[
                DAOPhotobookBookmarks
            ] = await DALPhotobookBookmarks.list_all(
                db_session,
                {"user_id": (FilterOp.EQ, logged_in_user_id)},
                order_by=[("created_at", OrderDirection.DESC)],
            )
            photobooks: list[DAOPhotobooks] = await DALPhotobooks.list_all(
                db_session,
                filters={
                    "id": (
                        FilterOp.IN,
                        [bookmark.photobook_id for bookmark in photobook_bookmarks],
                    ),
                    "status": (
                        FilterOp.NOT_IN,
                        [
                            PhotobookStatus.DELETED,
                            PhotobookStatus.PERMANENTLY_DELETED,
                        ],
                    ),
                },
            )
            return UserGetPhotobooksResponse(
                photobooks=await PhotobooksOverviewResponse.rendered_from_daos(
                    photobooks, db_session, self.app.asset_manager
                )
            )

    @enforce_response_model
    async def user_photobook_bookmark_new(
        self,
        request: Request,
        payload: UserBookmarkPhotobookInputPayload,
    ) -> PhotobookBookmarksOverviewResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            async with safe_commit(db_session):
                dao: DAOPhotobookBookmarks = await DALPhotobookBookmarks.create(
                    db_session,
                    DAOPhotobookBookmarksCreate(
                        user_id=logged_in_user_id,
                        photobook_id=payload.photobook_id,
                        source=payload.source_analytics,
                    ),
                )
            return PhotobookBookmarksOverviewResponse.from_dao(dao)

    @enforce_response_model
    async def user_photobook_bookmark_remove(
        self,
        request: Request,
        photobook_id: UUID,
    ) -> UserBookmarkPhotobookDeleteResponse:
        request_context = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            try:
                bookmarks = await DALPhotobookBookmarks.list_all(
                    db_session,
                    filters={
                        "user_id": (FilterOp.EQ, logged_in_user_id),
                        "photobook_id": (FilterOp.EQ, photobook_id),
                    },
                    limit=1,
                )

                if not bookmarks:
                    return UserBookmarkPhotobookDeleteResponse(
                        success=False,
                        error_message="Bookmark not found.",
                    )

                dao = bookmarks[0]

                async with safe_commit(db_session):
                    await DALPhotobookBookmarks.delete_by_id(db_session, dao.id)

                return UserBookmarkPhotobookDeleteResponse(success=True)
            except Exception as e:
                logging.exception(f"Failed to remove bookmark: {e}")
                return UserBookmarkPhotobookDeleteResponse(
                    success=False,
                    error_message="An unexpected error occurred.",
                )

    @enforce_response_model
    async def get_shared_with_me_photobooks(
        self, request: Request
    ) -> UserGetSharedWithMePhotobooksResponse:
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            current_user: DAOUsers = none_throws(
                await DALUsers.get_by_id(db_session, logged_in_user_id)
            )
            books_invited_by_user_id = await DALPhotobookShare.list_all(
                db_session,
                filters={
                    "invited_user_id": (FilterOp.EQ, current_user.id),
                },
            )
            books_invited_by_email = await DALPhotobookShare.list_all(
                db_session,
                filters={
                    "email": (FilterOp.EQ, current_user.email),
                },
            )
            book_ids_shared_with_me: set[UUID] = set(
                book.photobook_id
                for book in books_invited_by_user_id + books_invited_by_email
            )
            photobooks: list[DAOPhotobooks] = await DALPhotobooks.get_by_ids(
                db_session,
                list(book_ids_shared_with_me),
            )
            live_photobooks = [
                book
                for book in photobooks
                if book.status
                not in [
                    PhotobookStatus.DELETED,
                    PhotobookStatus.PERMANENTLY_DELETED,
                ]
            ]
            return UserGetSharedWithMePhotobooksResponse(
                photobooks=await PhotobooksOverviewResponse.rendered_from_daos(
                    live_photobooks, db_session, self.app.asset_manager
                )
            )

    @enforce_response_model
    async def get_dashboard(self, request: Request) -> UserDashboardResponse:
        """
        Returns the current user's username and all notifications related to them.
        "Related" means addressed directly by user_id OR by email.
        """
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        async with self.app.new_db_session() as db_session:
            # Load current user
            current_user: DAOUsers = none_throws(
                await DALUsers.get_by_id(db_session, logged_in_user_id)
            )

            # Prefer explicit username; fall back gracefully

            # Gather notifications by user_id
            by_user_id: list[DAONotifications] = await DALNotifications.list_all(
                db_session,
                filters={"recipient_id": (FilterOp.EQ, current_user.id)},
                order_by=[("created_at", OrderDirection.DESC)],
            )

            # De-duplicate (keep newest first). Uses DAO id as the identity key.
            merged: list[DAONotifications] = []
            seen_ids: set[UUID] = set()
            for n in by_user_id:
                if n.id not in seen_ids:
                    seen_ids.add(n.id)
                    merged.append(n)

            # Optionally, ensure final sort by created_at desc
            merged.sort(key=lambda n: n.created_at, reverse=True)

            return UserDashboardResponse(
                username=current_user.name,
                bmc_link=current_user.bmc_link,
                notifications=await NotificationsOverviewResponse.rendered_from_daos(
                    merged,  # db_session
                ),
            )

    @enforce_response_model
    async def user_edit_username(
        self,
        request: Request,
        edit_request: UserDashboardEditRequest,
    ) -> UserEditUsernameResponse:
        """
        Allows the current user to update their username.
        """
        request_context: RequestContext = await self.get_request_context(request)
        logged_in_user_id = request_context.user_id_assert_logged_in

        # Basic validation — adjust rules as needed
        if not edit_request.username or len(edit_request.username.strip()) < 3:
            return UserEditUsernameResponse(
                success=False,
                error_message="Username must be at least 3 characters long.",
            )

        async with self.app.new_db_session() as db_session:
            try:
                current_user: DAOUsers = none_throws(
                    await DALUsers.get_by_id(db_session, logged_in_user_id)
                )

                # Update username
                current_user.name = edit_request.username.strip()
                current_user.bmc_link = edit_request.bmc_link

                async with safe_commit(db_session):
                    db_session.add(current_user)

                return UserEditUsernameResponse(
                    success=True,
                    username=current_user.name,
                    bmc_link=current_user.bmc_link,
                )

            except Exception as e:
                logging.exception(f"Failed to update username: {e}")
                return UserEditUsernameResponse(
                    success=False,
                    error_message="An unexpected error occurred.",
                )

    @unauthenticated_route
    @enforce_response_model
    async def get_user_bmc_link(self, owner_id: UUID) -> Optional[UserGetBMCLink]:
        """
        Public-ish user info endpoint used by the client to fetch creator metadata.
        Returns minimal fields: username (name) and bmc_link.
        """
        # If you need auth gating, keep get_request_context; otherwise it can be omitted.
        # request_context: RequestContext = await self.get_request_context(request)

        async with self.app.new_db_session() as db_session:
            owner_identity = await DALOwnerIdentities.list_all(
                db_session,
                {
                    "owner_id": (FilterOp.EQ, owner_id),
                    "kind": (FilterOp.EQ, IdentityKind.USER),
                },
                limit=1,
            )

            if not owner_identity:
                return None

            user = await DALUsers.get_by_id(db_session, owner_identity[0].identity)
            if user is None:
                return None

            return UserGetBMCLink(
                user_id=user.id,
                username=user.name,  # your schema uses `name` for display/username
                bmc_link=user.bmc_link,  # nullable
            )
