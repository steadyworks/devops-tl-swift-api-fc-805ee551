from uuid import UUID

from backend.db.session.factory import AsyncSessionFactory
from backend.lib.asset_manager.base import AssetManager
from backend.worker.process.types import WorkerProcessResources

from .base import AbstractJobProcessor
from .registry import JOB_TYPE_JOB_PROCESSOR_REGISTRY
from .types import JobInputPayload, JobOutputPayload, JobType


class JobProcessorFactory:
    @classmethod
    def new_processor(
        cls,
        job_id: UUID,
        job_type: JobType,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
        worker_process_resources: WorkerProcessResources,
    ) -> AbstractJobProcessor[
        JobInputPayload, JobOutputPayload, WorkerProcessResources
    ]:
        processor_cls = JOB_TYPE_JOB_PROCESSOR_REGISTRY.get(job_type)
        if processor_cls is None:
            raise Exception(f"{job_id} not found")

        return processor_cls(
            job_id=job_id,
            asset_manager=asset_manager,
            db_session_factory=db_session_factory,
            worker_process_resources=worker_process_resources,
        )
