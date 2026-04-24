from typing import TypeVar

from backend.worker.process.types import LocalWorkerProcessResources

from .base import AbstractJobProcessor
from .types import JobInputPayload, JobOutputPayload

TInputPayload = TypeVar("TInputPayload", bound=JobInputPayload, contravariant=True)
TOutputPayload = TypeVar("TOutputPayload", bound=JobOutputPayload, covariant=True)
TLocalWorkerProcessResources = TypeVar(
    "TLocalWorkerProcessResources", bound=LocalWorkerProcessResources
)


class LocalJobProcessor(
    AbstractJobProcessor[TInputPayload, TOutputPayload, TLocalWorkerProcessResources]
):
    pass
