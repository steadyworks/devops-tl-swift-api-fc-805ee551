from backend.db.session.factory import AsyncSessionFactory
from backend.lib.job_manager.types import JobQueue
from backend.lib.redis.factory import RedisClientFactory

from .base import AbstractWorkerProcess
from .types import RemoteIOBoundWorkerProcessResources


class RemoteJobIOBoundWorkerProcess(
    AbstractWorkerProcess[RemoteIOBoundWorkerProcessResources]
):
    def _get_num_concurrent_worker_tasks(self) -> int:
        return 6  # IO bound nature allows more concurrent workers

    def _get_job_queue(self) -> JobQueue:
        return JobQueue.REMOTE_MAIN_TASK_QUEUE_IO_BOUND

    def _create_redis_client_factory(self) -> RedisClientFactory:
        return RedisClientFactory.from_remote_defaults()

    def _create_db_session_factory(self) -> AsyncSessionFactory:
        return AsyncSessionFactory()

    async def _create_process_level_resources(
        self,
    ) -> RemoteIOBoundWorkerProcessResources:
        return RemoteIOBoundWorkerProcessResources()

    async def _destruct_process_level_resources(
        self, resources: RemoteIOBoundWorkerProcessResources
    ) -> None:
        pass
