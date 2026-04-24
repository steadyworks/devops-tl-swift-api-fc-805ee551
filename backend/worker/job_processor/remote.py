from typing import TypeVar

from backend.worker.process.types import RemoteWorkerProcessResources

from .base import AbstractJobProcessor
from .types import JobInputPayload, JobOutputPayload

TInputPayload = TypeVar("TInputPayload", bound=JobInputPayload, contravariant=True)
TOutputPayload = TypeVar("TOutputPayload", bound=JobOutputPayload, covariant=True)
TRemoteWorkerProcessResources = TypeVar(
    "TRemoteWorkerProcessResources", bound=RemoteWorkerProcessResources
)


class RemoteJobProcessor(
    AbstractJobProcessor[TInputPayload, TOutputPayload, TRemoteWorkerProcessResources]
):
    pass
