from backend.db.data_models import (
    DAOAssets,
    DAOJobEvents,
    DAOJobs,
    DAONotifications,
    DAOOwnerIdentities,
    DAOOwners,
    DAOPages,
    DAOPagesAssetsRel,
    DAOPhotobookBookmarks,
    DAOPhotobookComments,
    DAOPhotobooks,
    DAOPhotobooksAssetsRel,
    DAOPhotobookSettings,
    DAOPhotobookShare,
    DAOUsers,
)

from .assets import DALAssets
from .base import (
    AsyncPostgreSQLDAL,
    FilterOp,
    InvalidFilterFieldError,
    OrderDirection,
    locked_row_by_id,
    safe_commit,
    safe_transaction,
)
from .job_events import DALJobEvents
from .schemas import (
    DAOAssetsCreate,
    DAOAssetsUpdate,
    DAOJobEventsCreate,
    DAOJobsCreate,
    DAOJobsUpdate,
    DAONotificationsCreate,
    DAONotificationsUpdate,
    DAOOwnerIdentitiesCreate,
    DAOOwnerIdentitiesUpdate,
    DAOOwnersCreate,
    DAOOwnersUpdate,
    DAOPagesAssetsRelCreate,
    DAOPagesAssetsRelUpdate,
    DAOPagesCreate,
    DAOPagesUpdate,
    DAOPhotobookBookmarksCreate,
    DAOPhotobookBookmarksUpdate,
    DAOPhotobookCommentsCreate,
    DAOPhotobookCommentsUpdate,
    DAOPhotobooksAssetsRelCreate,
    DAOPhotobooksAssetsRelUpdate,
    DAOPhotobooksCreate,
    DAOPhotobookSettingsCreate,
    DAOPhotobookSettingsUpdate,
    DAOPhotobookShareCreate,
    DAOPhotobookShareUpdate,
    DAOPhotobooksUpdate,
    DAOUsersCreate,
    DAOUsersUpdate,
)


class DALJobs(AsyncPostgreSQLDAL[DAOJobs, DAOJobsCreate, DAOJobsUpdate]):
    model = DAOJobs


class DALPages(AsyncPostgreSQLDAL[DAOPages, DAOPagesCreate, DAOPagesUpdate]):
    model = DAOPages


class DALPagesAssetsRel(
    AsyncPostgreSQLDAL[
        DAOPagesAssetsRel, DAOPagesAssetsRelCreate, DAOPagesAssetsRelUpdate
    ]
):
    model = DAOPagesAssetsRel


class DALPhotobooks(
    AsyncPostgreSQLDAL[DAOPhotobooks, DAOPhotobooksCreate, DAOPhotobooksUpdate]
):
    model = DAOPhotobooks


class DALUsers(AsyncPostgreSQLDAL[DAOUsers, DAOUsersCreate, DAOUsersUpdate]):
    model = DAOUsers


class DALPhotobookBookmarks(
    AsyncPostgreSQLDAL[
        DAOPhotobookBookmarks,
        DAOPhotobookBookmarksCreate,
        DAOPhotobookBookmarksUpdate,
    ]
):
    model = DAOPhotobookBookmarks


class DALPhotobookSettings(
    AsyncPostgreSQLDAL[
        DAOPhotobookSettings,
        DAOPhotobookSettingsCreate,
        DAOPhotobookSettingsUpdate,
    ]
):
    model = DAOPhotobookSettings


class DALPhotobookShare(
    AsyncPostgreSQLDAL[
        DAOPhotobookShare, DAOPhotobookShareCreate, DAOPhotobookShareUpdate
    ]
):
    model = DAOPhotobookShare


class DALPhotobookComments(
    AsyncPostgreSQLDAL[
        DAOPhotobookComments,
        DAOPhotobookCommentsCreate,
        DAOPhotobookCommentsUpdate,
    ]
):
    model = DAOPhotobookComments


class DALPhotobooksAssetsRel(
    AsyncPostgreSQLDAL[
        DAOPhotobooksAssetsRel,
        DAOPhotobooksAssetsRelCreate,
        DAOPhotobooksAssetsRelUpdate,
    ]
):
    model = DAOPhotobooksAssetsRel


class DALNotifications(
    AsyncPostgreSQLDAL[DAONotifications, DAONotificationsCreate, DAONotificationsUpdate]
):
    model = DAONotifications


class DALOwners(AsyncPostgreSQLDAL[DAOOwners, DAOOwnersCreate, DAOOwnersUpdate]):
    model = DAOOwners


class DALOwnerIdentities(
    AsyncPostgreSQLDAL[
        DAOOwnerIdentities, DAOOwnerIdentitiesCreate, DAOOwnerIdentitiesUpdate
    ]
):
    model = DAOOwnerIdentities


__all__ = [
    ##########################################################
    # DALs
    ##########################################################
    "DALAssets",
    "DALJobs",
    "DALJobEvents",
    "DALPages",
    "DALPagesAssetsRel",
    "DALPhotobooks",
    "DALPhotobookBookmarks",
    "DALPhotobookSettings",
    "DALPhotobookComments",
    "DALPhotobooksAssetsRel",
    "DALNotifications",
    "DALOwners",
    "DALOwnerIdentities",
    ##########################################################
    # DAL base
    ##########################################################
    "AsyncPostgreSQLDAL",
    "FilterOp",
    "InvalidFilterFieldError",
    "OrderDirection",
    ##########################################################
    # ORM objects
    ##########################################################
    "DAOAssets",
    "DAOJobs",
    "DAOJobEvents",
    "DAOPages",
    "DAOPagesAssetsRel",
    "DAOPhotobooks",
    "DAOUsers",
    "DAOPhotobookBookmarks",
    "DAOPhotobookSettings",
    "DAOPhotobookComments",
    "DAOPhotobooksAssetsRel",
    ##########################################################
    # Schemas
    ##########################################################
    "DAOAssetsCreate",
    "DAOAssetsUpdate",
    "DAOJobsCreate",
    "DAOJobsUpdate",
    "DAOJobEventsCreate",
    # "DAOJobEventsUpdate",   # Updating job events is not allowed, as it's an append-only log trail
    "DAOPagesCreate",
    "DAOPagesUpdate",
    "DAOPagesAssetsRelCreate",
    "DAOPagesAssetsRelUpdate",
    "DAOPhotobooksCreate",
    "DAOPhotobooksUpdate",
    "DAOUsersCreate",
    "DAOUsersUpdate",
    "DAOPhotobookBookmarksUpdate",
    "DAOPhotobookBookmarksCreate",
    "DAOPhotobookSettingsUpdate",
    "DAOPhotobookSettingsCreate",
    "DAOPhotobookCommentsUpdate",
    "DAOPhotobookCommentsCreate",
    "DAOPhotobooksAssetsRelUpdate",
    "DAOPhotobooksAssetsRelCreate",
    "DAOOwnersUpdate",
    "DAOOwnersCreate",
    "DAOOwnerIdentitiesUpdate",
    "DAOOwnerIdentitiesCreate",
    ##########################################################
    # Utils
    ##########################################################
    "safe_commit",
    "safe_transaction",
    "locked_row_by_id",
]
