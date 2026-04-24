import asyncio
import getpass
import logging
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALJobEvents,
    DALJobs,
    DAOJobEventsCreate,
    DAOJobsCreate,
    DAOJobsUpdate,
)
from backend.db.dal.base import safe_commit
from backend.db.data_models import ActorType, JobEventAction, JobStatus
from backend.env_loader import EnvLoader
from backend.lib.redis.factory import SafeRedisClient
from backend.worker.job_processor.registry import JOB_TYPE_INPUT_PAYLOAD_TYPE_REGISTRY
from backend.worker.job_processor.types import JobInputPayload, JobType

from .types import JobQueue

DEFAULT_DEQUEUE_POLL_TIMEOUT_SECS = 5


class RedisJobPayload(BaseModel):
    job_id: UUID
    job_type: str
    job_payload_raw_json: str


class JobManager:
    def __init__(self, redis_client: SafeRedisClient, queue: JobQueue) -> None:
        self._redis_client = redis_client
        self._redis_queue_name = self._build_queue_name(queue)
        logging.info(f"[job manager] started on queue: {self._redis_queue_name}")
        self._job_payload_cache: dict[UUID, RedisJobPayload] = dict()
        self._job_payload_cache_lock = asyncio.Lock()

    @classmethod
    def _build_queue_name(cls, queue: JobQueue) -> str:
        environ_prefix = (
            "PROD_"
            if EnvLoader.get_optional("ENV") == "production"
            else f"DEV_{getpass.getuser().upper()}_"
        )
        return f"{environ_prefix}_{queue.value}"

    async def enqueue(
        self,
        job_type: JobType,
        job_payload: JobInputPayload,
        max_retries: int,  # FIXME: implement retry logic
        db_session: AsyncSession,
    ) -> UUID:
        # Step 1: Persist job in Postgres
        async with safe_commit(
            db_session, context="job creation DB update", raise_on_fail=True
        ):
            job_dao = await DALJobs.create(
                db_session,
                DAOJobsCreate(
                    job_type=job_type.value,
                    status=JobStatus.QUEUED,
                    user_id=job_payload.user_id,
                    owner_id=job_payload.owner_id,
                    input_payload=job_payload.model_dump(mode="json"),
                    retry_count=0,
                    max_retries=max_retries,
                    photobook_id=job_payload.originating_photobook_id,
                ),
            )

        redis_payload = RedisJobPayload(
            job_id=job_dao.id,
            job_type=job_type.value,
            job_payload_raw_json=JOB_TYPE_INPUT_PAYLOAD_TYPE_REGISTRY[
                job_type
            ].model_dump_json(job_payload),
        )
        redis_payload_raw_json = None
        try:
            redis_payload_raw_json = redis_payload.model_dump_json()
            await self._redis_client.safe_rpush(
                self._redis_queue_name, redis_payload_raw_json
            )
            logging.debug(
                f"[LocalJobManager] Enqueued job {job_dao.id} ({job_type.value}) to Redis queue "
                f"{self._redis_queue_name}, redis_payload: {redis_payload_raw_json}"
            )
            async with safe_commit(
                db_session, context="mark job as enqueued", raise_on_fail=False
            ):
                await DALJobEvents.create(
                    db_session,
                    DAOJobEventsCreate(
                        job_id=job_dao.id,
                        job_type=job_dao.job_type,
                        event_action=JobEventAction.JOB_QUEUED,
                        actor_type=ActorType.JOB_MANAGER,
                        photobook_id=job_dao.photobook_id,
                    ),
                )
        except Exception as e:
            logging.exception(f"[job manager] Failed to enqueue job {job_dao.id}: {e}")
            async with safe_commit(
                db_session, context="mark job as failed to enqueue", raise_on_fail=False
            ):
                await DALJobs.update_by_id(
                    db_session,
                    job_dao.id,
                    DAOJobsUpdate(
                        status=JobStatus.ENQUEUE_FAILED,
                    ),
                )
                await DALJobEvents.create(
                    db_session,
                    DAOJobEventsCreate(
                        job_id=job_dao.id,
                        job_type=job_type.value,
                        event_action=JobEventAction.JOB_ENQUEUE_FAILED,
                        message=str(e),
                        extra={
                            "redis_payload": redis_payload_raw_json,
                        },
                        actor_type=ActorType.JOB_MANAGER,
                        photobook_id=job_dao.photobook_id,
                    ),
                )
            raise e
        return job_dao.id

    async def poll(
        self,
        timeout: int,
    ) -> Optional[UUID]:
        try:
            result = await asyncio.wait_for(
                self._redis_client.safe_blpop(self._redis_queue_name, timeout=timeout),
                timeout=timeout + 5,  # pad to account for reconnect etc.
            )
        except asyncio.TimeoutError:
            logging.warning(
                f"[job manager] Unexpected poll timeout after {timeout} secs..."
            )
            # Redis may be stuck, kill the task and let supervisor handle retry
            return None
        except Exception as e:
            logging.exception(f"[job manager] Unexpected exception occurred: {e}")
            raise e

        if not result:
            return None  # timeout occurred

        _queue_name, job_payload_str = result
        logging.debug(f"[job manager] polled from {_queue_name}: {job_payload_str}")
        try:
            redis_payload = RedisJobPayload.model_validate_json(job_payload_str)
            job_uuid = redis_payload.job_id
            async with self._job_payload_cache_lock:
                self._job_payload_cache[job_uuid] = redis_payload
            return job_uuid
        except Exception as e:
            logging.warning(f"[LocalJobManager] Failed to decode job payload: {e}")
            return None

    async def claim(
        self,
        job_id: UUID,
        db_session: AsyncSession,
    ) -> tuple[JobType, JobInputPayload]:
        job_payload = None
        async with self._job_payload_cache_lock:
            job_payload = self._job_payload_cache.pop(job_id, None)

        if job_payload is None:
            raise KeyError(
                f"[job manager] Unexpected error. Job UUID: {job_id} not found in cache"
            )

        job_type_enum = JobType(job_payload.job_type)
        job_payload_raw_json = job_payload.job_payload_raw_json
        input_payload = JOB_TYPE_INPUT_PAYLOAD_TYPE_REGISTRY[
            job_type_enum
        ].model_validate_json(job_payload_raw_json)

        async with safe_commit(
            db_session, context="job dequeued status update", raise_on_fail=False
        ):
            # Update job status in Postgres
            job_dao = await DALJobs.update_by_id(
                db_session,
                job_id,
                DAOJobsUpdate(
                    status=JobStatus.DEQUEUED,
                ),
            )
            await DALJobEvents.create(
                db_session,
                DAOJobEventsCreate(
                    job_id=job_id,
                    job_type=job_type_enum.value,
                    event_action=JobEventAction.JOB_DEQUEUED,
                    extra={
                        "redis_payload": job_payload.job_payload_raw_json,
                    },
                    actor_type=ActorType.JOB_MANAGER,
                    photobook_id=job_dao.photobook_id,
                ),
            )

        return job_type_enum, input_payload
