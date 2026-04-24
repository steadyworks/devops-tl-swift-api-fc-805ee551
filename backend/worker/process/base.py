# pyright: reportUnnecessaryComparison=false
import asyncio
import logging
import random
import signal
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from multiprocessing import Process
from multiprocessing.connection import Connection
from types import FrameType, TracebackType
from typing import Generic, Optional, Type, TypeVar
from uuid import UUID

from redis.exceptions import ConnectionError as RedisConnErr
from redis.exceptions import TimeoutError as RedisTimeoutErr

from backend.db.dal import DALJobEvents, DALJobs, DAOJobEventsCreate, DAOJobsUpdate
from backend.db.dal.base import safe_commit
from backend.db.data_models import ActorType, JobEventAction, JobStatus
from backend.db.session.factory import AsyncSessionFactory
from backend.lib.asset_manager.base import AssetManager
from backend.lib.asset_manager.factory import AssetManagerFactory
from backend.lib.job_manager.base import JobManager
from backend.lib.job_manager.types import JobQueue
from backend.lib.redis.factory import RedisClientFactory
from backend.lib.utils.common import none_throws, utcnow
from backend.logging_utils import configure_logging_env
from backend.worker.job_processor.factory import JobProcessorFactory
from backend.worker.job_processor.types import JobInputPayload, JobType

from .types import WorkerProcessResources

MAX_CONCURRENT_WORKER_TASKS = 20
MAX_JOB_TIMEOUT_SECS = 300  # 5 mins
SEND_HEARTBEAT_EVERY_SECS = 1
POLL_SHUTDOWN_EVERY_SECS = 1
HEARTBEAT_PING_MSG = "ping"
SHUTDOWN_SIGNAL_MSG = "shutdown"
READY_SIGNAL_MSG = "ready"
JOB_MANAGER_POLL_TIMEOUT_SECS = 5
WORKER_RESTART_BACKOFF_SECS = 1


JOB_POLLING_MAX_BACKOFF_SECS = 30
JOB_POLLING_INITIAL_BACKOFF_SECS = 0.5
JOB_POLLING_BACKOFF_MULTIPLIER = 2.0
JOB_POLLING_JITTER_FRACTION = 0.4  # ±40 %


class BaseWorkerProcess(Process, ABC):
    def __init__(self, heartbeat_connection: Connection, name: str = "worker") -> None:
        super().__init__()
        self.name = name
        self.heartbeat_connection = heartbeat_connection

    @abstractmethod
    def run(self) -> None: ...


TSharedProcessLevelResources = TypeVar(
    "TSharedProcessLevelResources", bound=WorkerProcessResources
)


class AbstractWorkerProcess(BaseWorkerProcess, Generic[TSharedProcessLevelResources]):
    _process_level_resources: Optional[TSharedProcessLevelResources] = None

    def __init__(self, heartbeat_connection: Connection, name: str = "worker") -> None:
        # Runs in the parent process
        super().__init__(heartbeat_connection, name)

    @abstractmethod
    def _get_num_concurrent_worker_tasks(self) -> int: ...

    @abstractmethod
    def _create_redis_client_factory(self) -> RedisClientFactory: ...

    @abstractmethod
    def _get_job_queue(self) -> JobQueue: ...

    @abstractmethod
    def _create_db_session_factory(self) -> AsyncSessionFactory: ...

    @abstractmethod
    async def _create_process_level_resources(
        self,
    ) -> TSharedProcessLevelResources:
        # Initialize any process level shared resources,
        # and return a resource envelop exposed to job processors
        ...

    @abstractmethod
    async def _destruct_process_level_resources(
        self, resources: TSharedProcessLevelResources
    ) -> None:
        # Destruct any process level shared resources, as well as
        # resources inside the resource envelop
        ...

    async def __initialize_process_level_resources(self) -> None:
        logging.info(f"[{self.name}] Initializing process level resources...")
        self._process_level_resources = await self._create_process_level_resources()

    async def __deallocate_process_level_resources(self) -> None:
        logging.info(f"[{self.name}] Destructing process level resources...")
        if self._process_level_resources is not None:
            await self._destruct_process_level_resources(self._process_level_resources)

    def _start_heartbeat_ping_thread(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
        def send_heartbeat(_shutdown_event: asyncio.Event) -> None:
            try:
                while not _shutdown_event.is_set():
                    try:
                        self.heartbeat_connection.send(HEARTBEAT_PING_MSG)
                        time.sleep(SEND_HEARTBEAT_EVERY_SECS)
                    except Exception:
                        logging.warning(
                            f"[{self.name}] Heartbeat pipe closed (send)"
                        )  # parent closed pipe
                        _shutdown_event.set()
                        break
            except Exception as e:
                logging.exception(f"[{self.name}] Heartbeat thread crashed: {e}")

        threading.Thread(
            target=send_heartbeat, args=(shutdown_event,), daemon=True
        ).start()

    def _start_heartbeat_shutdown_monitor_thread(
        self,
        shutdown_event: asyncio.Event,
    ) -> None:
        def monitor_shutdown(_shutdown_event: asyncio.Event) -> None:
            while not _shutdown_event.is_set():
                try:
                    if self.heartbeat_connection.poll(timeout=POLL_SHUTDOWN_EVERY_SECS):
                        msg = self.heartbeat_connection.recv()
                        if msg == SHUTDOWN_SIGNAL_MSG:
                            logging.info(f"[{self.name}] Received shutdown signal")
                            _shutdown_event.set()
                            break
                except (EOFError, OSError):
                    logging.warning(f"[{self.name}] Heartbeat pipe closed")
                    _shutdown_event.set()
                    break
                time.sleep(0.1)

        threading.Thread(
            target=monitor_shutdown, args=(shutdown_event,), daemon=True
        ).start()

    def run(self) -> None:
        # Run in child process
        try:
            configure_logging_env()
            logging.info(f"[{self.name}] Worker started with PID {self.pid}")

            setup_crash_logging(self.name)

            # Initialize shutdown event
            shutdown_event = asyncio.Event()

            def _sigterm_handler(_signum: int, _frame: FrameType | None) -> None:
                """Handle SIGTERM/SIGINT by asking the main loop to exit."""
                shutdown_event.set()

            # Register lightweight, worker-local handlers
            signal.signal(signal.SIGTERM, _sigterm_handler)
            signal.signal(signal.SIGINT, _sigterm_handler)

            # Initialize resources or resource factories shared by all tasks
            asset_manager = AssetManagerFactory().create()
            db_session_factory = self._create_db_session_factory()

            try:
                self.heartbeat_connection.send(READY_SIGNAL_MSG)
            except Exception:
                # parent died or pipe closed – nothing more we can do
                logging.warning(f"[{self.name}] Could not send READY_SIGNAL_MSG")

            # Initialize heartbeat ping and shutdown monitor threads
            self._start_heartbeat_ping_thread(shutdown_event)
            self._start_heartbeat_shutdown_monitor_thread(shutdown_event)

            async def _wrapped_main(
                _asset_manager: AssetManager,
                _db_session_factory: AsyncSessionFactory,
                _shutdown_event: asyncio.Event,
            ) -> None:
                redis_client_factory = self._create_redis_client_factory()
                redis_client = redis_client_factory.new_redis_client()
                job_manager = JobManager(redis_client, self._get_job_queue())
                await self.__initialize_process_level_resources()
                try:
                    await self._supervised_main_loop_forever(
                        _asset_manager,
                        job_manager,
                        _db_session_factory,
                        _shutdown_event,
                    )
                finally:
                    logging.info(
                        f"[{self.name}] Closing redis clients, pools, and other process level resources."
                    )
                    await self.__deallocate_process_level_resources()
                    await redis_client.close()
                    await redis_client_factory.close_pool()

            asyncio.run(
                _wrapped_main(
                    asset_manager,
                    db_session_factory,
                    shutdown_event,
                )
            )
        except Exception as e:
            logging.exception(f"[{self.name}] Worker crashed: {e}")
            raise e
        finally:
            logging.info(f"[{self.name}] Exiting run() — process will terminate.")

    async def _supervised_main_loop_forever(
        self,
        asset_manager: AssetManager,
        job_manager: JobManager,
        db_session_factory: AsyncSessionFactory,
        shutdown_event: asyncio.Event,
    ) -> None:
        logging.info(f"[{self.name}] Started worker process (PID={self.pid})")

        try:
            # Launch all workers + monitor
            await self._run_worker_supervisor_loop(
                asset_manager, job_manager, db_session_factory, shutdown_event
            )
        except asyncio.CancelledError as e:
            logging.info(f"[{self.name}] Supervisor received cancel signal: {e}")
        except Exception as e:
            logging.info(f"[{self.name}] Supervisor unexpected exception: {e}")

        logging.info(f"[{self.name}] All tasks shut down cleanly")

    async def _run_worker_supervisor_loop(
        self,
        asset_manager: AssetManager,
        job_manager: JobManager,
        db_session_factory: AsyncSessionFactory,
        shutdown_event: asyncio.Event,
    ) -> None:
        running_tasks: dict[int, asyncio.Task[None]] = {}

        requested_num_concurrent_worker_tasks = self._get_num_concurrent_worker_tasks()
        assert 0 < requested_num_concurrent_worker_tasks < MAX_CONCURRENT_WORKER_TASKS

        # Start all workers
        for i in range(requested_num_concurrent_worker_tasks):
            running_tasks[i] = asyncio.create_task(
                self._spawn_worker_forever(
                    i,
                    asset_manager,
                    job_manager,
                    db_session_factory,
                    shutdown_event,
                )
            )

        # Monitor loop
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
            for i, task in list(running_tasks.items()):
                if task.done():
                    exc = task.exception()
                    if exc:
                        logging.error(
                            f"[{self.name}] Worker-{i} exited with error: {exc}"
                        )
                    else:
                        logging.warning(
                            f"[{self.name}] Worker-{i} exited cleanly (unexpected)"
                        )

                    # Restart
                    logging.info(f"[{self.name}] Restarting Worker-{i}")
                    if not shutdown_event.is_set():
                        running_tasks[i] = asyncio.create_task(
                            self._spawn_worker_forever(
                                i,
                                asset_manager,
                                job_manager,
                                db_session_factory,
                                shutdown_event,
                            )
                        )

        # Shutdown triggered: cancel all
        logging.info(f"[{self.name}] Cancelling all workers...")
        for task in running_tasks.values():
            task.cancel()

        await asyncio.gather(*running_tasks.values(), return_exceptions=True)
        logging.info(f"[{self.name}] All workers shut down cleanly")

    async def _spawn_worker_forever(
        self,
        i: int,
        asset_manager: AssetManager,
        job_manager: JobManager,
        db_session_factory: AsyncSessionFactory,
        shutdown_event: asyncio.Event,
    ) -> None:
        while not shutdown_event.is_set():
            try:
                logging.info(f"[{self.name}-thread_{i}] Spawning worker-{i}")
                await self._job_worker_main_loop(
                    i,
                    job_manager,
                    asset_manager,
                    db_session_factory,
                    shutdown_event,
                )
            except Exception as e:
                logging.exception(
                    f"[{self.name}-thread_{i}] Worker-{i} crashed: {e}. Restarting after delay."
                )
                await asyncio.sleep(WORKER_RESTART_BACKOFF_SECS)  # optional backoff

    async def _job_worker_main_loop(
        self,
        worker_thread_id: int,
        job_manager: JobManager,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
        shutdown_event: asyncio.Event,
    ) -> None:
        backoff: float = JOB_POLLING_INITIAL_BACKOFF_SECS
        while not shutdown_event.is_set():
            try:
                logging.debug(
                    f"[{self.name}-thread_{worker_thread_id}] Polling from redis"
                )
                job_uuid = await job_manager.poll(timeout=JOB_MANAGER_POLL_TIMEOUT_SECS)
                logging.debug(
                    f"[{self.name}-thread_{worker_thread_id}] Received job from redis: {job_uuid}"
                )

                # success ⇒ reset back-off
                backoff = JOB_POLLING_INITIAL_BACKOFF_SECS

                if shutdown_event.is_set():
                    break
                if job_uuid is None:
                    continue

                await self._process_job_polled_from_redis(
                    worker_thread_id,
                    job_uuid,
                    job_manager,
                    asset_manager,
                    db_session_factory,
                )
            except asyncio.CancelledError:
                logging.info(f"[{self.name}-thread_{worker_thread_id}] Cancelled")
                raise
            except (RedisConnErr, RedisTimeoutErr) as e:
                # Log once per attempt with current delay
                logging.warning(
                    "[%s-thread_%d] Redis unavailable: %s – retrying in %.2fs",
                    self.name,
                    worker_thread_id,
                    e,
                    backoff,
                )
                await asyncio.sleep(
                    backoff
                    * (1 + (random.random() - 0.5) * 2 * JOB_POLLING_JITTER_FRACTION)
                )
                backoff = min(
                    backoff * JOB_POLLING_BACKOFF_MULTIPLIER,
                    JOB_POLLING_MAX_BACKOFF_SECS,
                )

            except Exception:
                logging.exception(
                    f"[{self.name}-thread_{worker_thread_id}] Unexpected error"
                )
                await asyncio.sleep(1)  # tiny pause so we don’t loop at warp speed

    async def _process_job_polled_from_redis(
        self,
        worker_thread_id: int,
        job_uuid: UUID,
        job_manager: JobManager,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
    ) -> None:
        job_type, job_input_payload = None, None
        try:
            async with db_session_factory.new_session() as db_session:
                job_type, job_input_payload = await job_manager.claim(
                    job_uuid, db_session=db_session
                )
                if job_type is None or job_input_payload is None:
                    logging.warning(
                        f"[{self.name}-thread_{worker_thread_id}] Received incomplete job {job_uuid}"
                    )
                    await self._update_job_status_as_error(
                        job_id=job_uuid,
                        job_type=job_type,
                        worker_thread_id=worker_thread_id,
                        db_session_factory=db_session_factory,
                        error_message="Claimed job missing type or input payload",
                    )
                    return
        except asyncio.CancelledError:
            error_message = (
                f"[{self.name}-thread_{worker_thread_id}] Cancelled while"
                f"claiming job {job_uuid}"
            )
            logging.warning(error_message)
            await self._update_job_status_as_error(
                job_id=job_uuid,
                job_type=job_type,
                worker_thread_id=worker_thread_id,
                db_session_factory=db_session_factory,
                error_message=error_message,
            )
            raise  # Bubble up task cancelation
        except Exception as e:  # Unexpected exception
            tb = traceback.format_exc()
            error_message = (
                f"[{self.name}-thread_{worker_thread_id}] Unexpected exception "
                f"claiming job {job_uuid}, e: {e}, tb: {tb}"
            )
            logging.exception(error_message)
            await self._update_job_status_as_error(
                job_id=job_uuid,
                job_type=job_type,
                worker_thread_id=worker_thread_id,
                db_session_factory=db_session_factory,
                error_message=error_message,
                traceback=tb,
            )
            return  # Not successfully claimed

        try:
            await asyncio.wait_for(
                self._handle_task(
                    worker_thread_id,
                    job_uuid,
                    job_type,
                    job_input_payload,
                    asset_manager,
                    db_session_factory,
                ),
                timeout=MAX_JOB_TIMEOUT_SECS,
            )
        except asyncio.CancelledError:
            error_message = (
                f"[{self.name}-thread_{worker_thread_id}] "
                f"Cancelled while running job {job_uuid}"
            )
            logging.warning(error_message)
            await self._update_job_status_as_error(
                job_id=job_uuid,
                job_type=job_type,
                worker_thread_id=worker_thread_id,
                db_session_factory=db_session_factory,
                error_message=error_message,
            )
            raise  # Bubble up task cancelation
        except asyncio.TimeoutError:
            error_message = (
                f"[{self.name}-thread_{worker_thread_id}] Job timed out after "
                f"{MAX_JOB_TIMEOUT_SECS}s, job_id: {job_uuid} payload: "
                f"{job_input_payload.model_dump_json() if job_input_payload else '<missing payload>'}"
            )
            logging.warning(error_message)
            await self._update_job_status_as_error(
                job_id=job_uuid,
                job_type=job_type,
                worker_thread_id=worker_thread_id,
                db_session_factory=db_session_factory,
                error_message=error_message,
            )
        except Exception as e:
            tb = traceback.format_exc()  # full traceback string
            error_message = (
                f"[{self.name}-thread_{worker_thread_id}] Job failed: job_id: {job_uuid}\n"
                f"Payload: {job_input_payload.model_dump_json() if job_input_payload else '<missing payload>'}\n"
                f"Exception: {e}\n"
                f"Traceback:\n{tb}"
            )
            logging.warning(error_message)
            await self._update_job_status_as_error(
                job_id=job_uuid,
                job_type=job_type,
                worker_thread_id=worker_thread_id,
                db_session_factory=db_session_factory,
                error_message=error_message,
                traceback=tb,
            )

    async def _handle_task(
        self,
        worker_thread_id: int,
        job_uuid: UUID,
        job_type: JobType,
        job_input_payload: JobInputPayload,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
    ) -> None:
        try:
            async with db_session_factory.new_session() as db_session:
                async with safe_commit(
                    db_session, context="job processing DB update", raise_on_fail=False
                ):
                    # Update job status in Postgres
                    job_dao = await DALJobs.update_by_id(
                        db_session,
                        job_uuid,
                        DAOJobsUpdate(
                            status=JobStatus.PROCESSING,
                            started_at=utcnow(),
                        ),
                    )
                    await DALJobEvents.create(
                        db_session,
                        DAOJobEventsCreate(
                            job_id=job_uuid,
                            job_type=job_type.value,
                            event_action=JobEventAction.ATTEMPT_STARTED,
                            actor_type=ActorType.JOB_PROCESSOR,
                            photobook_id=job_dao.photobook_id,
                        ),
                    )

            logging.debug(
                f"[{self.name}-thread_{worker_thread_id}] Processing {job_uuid}, job type: {job_type}"
            )
            job_processor = JobProcessorFactory.new_processor(
                job_uuid,
                job_type,
                asset_manager,
                db_session_factory,
                none_throws(self._process_level_resources),
            )
            result = await job_processor.process(job_input_payload)
            logging.debug(
                f"[{self.name}-thread_{worker_thread_id}] Processed {job_uuid}, job type: {job_type}"
            )

            async with db_session_factory.new_session() as db_session:
                async with safe_commit(
                    db_session, context="job done DB update", raise_on_fail=True
                ):
                    result_payload_dump = result.model_dump(mode="json")
                    # Update job status in Postgres
                    job_dao = await DALJobs.update_by_id(
                        db_session,
                        job_uuid,
                        DAOJobsUpdate(
                            status=JobStatus.DONE,
                            completed_at=utcnow(),
                            result_payload=result_payload_dump,
                        ),
                    )
                    await DALJobEvents.create(
                        db_session,
                        DAOJobEventsCreate(
                            job_id=job_uuid,
                            job_type=job_type.value,
                            event_action=JobEventAction.JOB_SUCCEEDED,
                            actor_type=ActorType.JOB_PROCESSOR,
                            extra={"result_payload": result_payload_dump},
                            photobook_id=job_dao.photobook_id,
                        ),
                    )
        except asyncio.CancelledError:
            logging.info(
                f"[{self.name}-thread_{worker_thread_id}] Cancelled while processing job {job_uuid}"
            )
            raise
        except Exception as e:
            logging.warning(
                f"[{self.name}-thread_{worker_thread_id}] Failed job {job_uuid}: {e}"
            )
            raise e

    async def _update_job_status_as_error(
        self,
        job_id: UUID,
        job_type: Optional[JobType],
        worker_thread_id: int,
        db_session_factory: AsyncSessionFactory,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> None:
        try:
            async with db_session_factory.new_session() as db_session:
                async with safe_commit(
                    db_session,
                    context="mark job status as failed DB update",
                    raise_on_fail=False,
                ):
                    # Update job status in Postgres
                    job_dao = await DALJobs.update_by_id(
                        db_session,
                        job_id,
                        DAOJobsUpdate(
                            status=JobStatus.ERROR,
                            error_message=error_message,
                        ),
                    )
                    await DALJobEvents.create(
                        db_session,
                        DAOJobEventsCreate(
                            job_id=job_id,
                            job_type=None if job_type is None else job_type.value,
                            event_action=JobEventAction.ATTEMPT_FAILED,
                            message=error_message,
                            extra={
                                "traceback": traceback,
                            },
                            actor_type=ActorType.JOB_PROCESSOR,
                            photobook_id=job_dao.photobook_id,
                        ),
                    )
        except Exception as inner:
            logging.warning(
                f"[{self.name}-thread_{worker_thread_id}] Failed to mark job {job_id} as error: {inner}"
            )


def setup_crash_logging(worker_name: str) -> None:
    def handle_exception(
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_traceback: Optional[TracebackType],
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return  # Let the supervisor handle shutdown

        logging.critical(
            f"[{worker_name}] Uncaught exception:\n"
            f"{''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))}"
        )
        sys.exit(1)  # sys.exit is annotated as NoReturn

    sys.excepthook = handle_exception
