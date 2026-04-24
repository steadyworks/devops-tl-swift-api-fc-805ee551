from typing import Optional, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.worker.job_processor.types import JobInputPayload, JobType


class JobManagerProtocol(Protocol):
    async def enqueue(
        self,
        job_type: JobType,
        job_payload: JobInputPayload,
        max_retries: int,
        db_session: AsyncSession,
    ) -> UUID: ...

    async def poll(self, timeout: int) -> Optional[UUID]: ...

    async def claim(
        self,
        job_id: UUID,
        db_session: AsyncSession,
    ) -> tuple[JobType, JobInputPayload]: ...
