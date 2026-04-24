from backend.db.session.factory import AsyncSessionFactory
from backend.lib.geo.radar import RadarHttpClient
from backend.lib.job_manager.types import JobQueue
from backend.lib.redis.factory import RedisClientFactory

from .base import AbstractWorkerProcess
from .types import RemoteCPUBoundWorkerProcessResources


class RemoteJobCPUBoundWorkerProcess(
    AbstractWorkerProcess[RemoteCPUBoundWorkerProcessResources]
):
    def _get_num_concurrent_worker_tasks(self) -> int:
        # CPU bound nature allows less concurrent workers
        # We will spin up 2 processes for process level crash isolation.
        return 1

    def _get_job_queue(self) -> JobQueue:
        return JobQueue.REMOTE_MAIN_TASK_QUEUE_CPU_BOUND

    def _create_redis_client_factory(self) -> RedisClientFactory:
        return RedisClientFactory.from_remote_defaults()

    def _create_db_session_factory(self) -> AsyncSessionFactory:
        return AsyncSessionFactory()

    async def _create_process_level_resources(
        self,
    ) -> RemoteCPUBoundWorkerProcessResources:
        return RemoteCPUBoundWorkerProcessResources(
            radar_client=RadarHttpClient(
                max_retries=3,
                base_backoff=0.2,
                max_concurrent_requests=5,
                rate_limit_qps=10,
            )
        )

    async def _destruct_process_level_resources(
        self, resources: RemoteCPUBoundWorkerProcessResources
    ) -> None:
        await resources.radar_client.close()
