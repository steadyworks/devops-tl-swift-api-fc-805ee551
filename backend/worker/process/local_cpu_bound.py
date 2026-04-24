from typing import Optional

from backend.db.session.factory import AsyncSessionFactory
from backend.lib.job_manager.base import JobManager
from backend.lib.job_manager.types import JobQueue
from backend.lib.redis.factory import RedisClientFactory, SafeRedisClient

from .base import AbstractWorkerProcess
from .types import LocalCPUBoundWorkerProcessResources


class LocalJobCPUBoundWorkerProcess(
    AbstractWorkerProcess[LocalCPUBoundWorkerProcessResources]
):
    _remote_redis_io_bound_client_factory: Optional[RedisClientFactory] = None
    _remote_redis_client: Optional[SafeRedisClient] = None
    _remote_redis_io_bound_job_manager: Optional[JobManager] = None

    def _get_num_concurrent_worker_tasks(self) -> int:
        # We expect local jobs to be mainly CPU bound, thus limiting concurrency.
        # We will spin up 2 processes for process level crash isolation.
        return 1

    def _get_job_queue(self) -> JobQueue:
        return JobQueue.LOCAL_MAIN_TASK_QUEUE_CPU_BOUND

    def _create_redis_client_factory(self) -> RedisClientFactory:
        return RedisClientFactory.from_local_defaults()

    def _create_db_session_factory(self) -> AsyncSessionFactory:
        return AsyncSessionFactory()

    async def _create_process_level_resources(
        self,
    ) -> LocalCPUBoundWorkerProcessResources:
        self._remote_redis_io_bound_client_factory = (
            RedisClientFactory.from_remote_defaults()
        )
        self._remote_redis_client = (
            self._remote_redis_io_bound_client_factory.new_redis_client()
        )
        return LocalCPUBoundWorkerProcessResources(
            remote_io_bound_job_manager=JobManager(
                self._remote_redis_client,
                JobQueue.REMOTE_MAIN_TASK_QUEUE_IO_BOUND,
            )
        )

    async def _destruct_process_level_resources(
        self, resources: LocalCPUBoundWorkerProcessResources
    ) -> None:
        if self._remote_redis_client is not None:
            await self._remote_redis_client.close()
        if self._remote_redis_io_bound_client_factory is not None:
            await self._remote_redis_io_bound_client_factory.close_pool()
