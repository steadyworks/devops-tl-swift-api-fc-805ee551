from typing import Any

from backend.worker.process.types import WorkerProcessResources

from .base import AbstractJobProcessor
from .remote_photobook_generation import RemotePhotobookGenerationJobProcessor
from .remote_post_process_uploaded_assets import (
    RemotePostProcessUploadedAssetsJobProcessor,
)
from .types import (
    JobInputPayload,
    JobOutputPayload,
    JobType,
    PhotobookGenerationInputPayload,
    PostProcessUploadedAssetsInputPayload,
)

JOB_TYPE_INPUT_PAYLOAD_TYPE_REGISTRY: dict[JobType, type[JobInputPayload]] = {
    JobType.REMOTE_PHOTOBOOK_GENERATION: PhotobookGenerationInputPayload,
    JobType.REMOTE_POST_PROCESS_UPLOADED_ASSETS: PostProcessUploadedAssetsInputPayload,
}


# Registry with erased generics
JOB_TYPE_JOB_PROCESSOR_REGISTRY: dict[
    JobType, type[AbstractJobProcessor[Any, JobOutputPayload, WorkerProcessResources]]
] = {
    # Local job processors
    # Remote job processors
    JobType.REMOTE_PHOTOBOOK_GENERATION: RemotePhotobookGenerationJobProcessor,
    JobType.REMOTE_POST_PROCESS_UPLOADED_ASSETS: RemotePostProcessUploadedAssetsJobProcessor,
}
