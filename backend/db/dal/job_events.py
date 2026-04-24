from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.data_models import DAOJobEvents
from backend.lib.utils.common import get_host_info

from .base import AsyncPostgreSQLDAL
from .schemas import DAOJobEventsCreate, DAOJobEventsUpdate


class DALJobEvents(
    AsyncPostgreSQLDAL[DAOJobEvents, DAOJobEventsCreate, DAOJobEventsUpdate]
):
    model = DAOJobEvents

    @classmethod
    async def create(
        cls, session: AsyncSession, obj_in: DAOJobEventsCreate
    ) -> DAOJobEvents:
        if obj_in.host is None:
            obj_in.host = get_host_info()
        return await super().create(session, obj_in)
