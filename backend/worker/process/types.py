from dataclasses import dataclass

from backend.lib.geo.radar_protocol import RadarHttpClientProtocol
from backend.lib.job_manager.protocol import JobManagerProtocol


#####################################################################################
# Worker process resources
#####################################################################################
@dataclass
class WorkerProcessResources:
    pass


@dataclass
class LocalWorkerProcessResources(WorkerProcessResources):
    pass


@dataclass
class RemoteWorkerProcessResources(WorkerProcessResources):
    pass


@dataclass
class LocalCPUBoundWorkerProcessResources(LocalWorkerProcessResources):
    remote_io_bound_job_manager: JobManagerProtocol


@dataclass
class RemoteCPUBoundWorkerProcessResources(RemoteWorkerProcessResources):
    radar_client: RadarHttpClientProtocol


@dataclass
class RemoteIOBoundWorkerProcessResources(RemoteWorkerProcessResources):
    pass
