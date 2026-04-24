# pylint: disable=protected-access
# pyright: reportPrivateUsage=false

import threading
import time
from multiprocessing import Pipe, Process, connection
from typing import Optional, cast

import pytest

from backend.worker.pool import WorkerPoolSupervisor
from backend.worker.process.base import BaseWorkerProcess


class FakeWorkerProcess:
    def __init__(self, conn: connection.Connection, name: str) -> None:
        self.conn = conn
        self.name = name
        self._proc_alive: bool = True
        self.pid: int = 12345

    def is_alive(self) -> bool:
        return self._proc_alive

    def terminate(self) -> None:
        self._proc_alive = False

    def join(self, timeout: Optional[float] = None) -> None:
        pass

    def kill(self) -> None:
        self._proc_alive = False

    def start(self) -> None:
        self.conn.send("ping")

    @property
    def exitcode(self) -> Optional[int]:
        return None if self._proc_alive else 1  # emulate a live process


def test_worker_starts_and_receives_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor = WorkerPoolSupervisor()

    def mock_start_worker(cls: type[BaseWorkerProcess], i: int) -> None:
        parent_conn, child_conn = Pipe()
        fake_proc = FakeWorkerProcess(parent_conn, f"worker-{cls.__name__}-{i}")
        supervisor.processes[cls][i] = cast("Process", fake_proc)
        supervisor.heartbeat_conns[cls][i] = parent_conn

        # simulate child process sending heartbeat shortly after start
        def send_ping() -> None:
            time.sleep(0.1)  # give time for conn.poll to register
            child_conn.send("ping")

        threading.Thread(target=send_ping, daemon=True).start()

    monkeypatch.setattr(supervisor, "_start_worker", mock_start_worker)

    supervisor._start_all_workers()

    for cls in supervisor.processes:
        p = supervisor.processes[cls][0]
        conn = supervisor.heartbeat_conns[cls][0]
        time.sleep(0.2)  # give time for background ping thread
        assert not supervisor._is_worker_dead(p, conn, cls, 0)

    supervisor.shutdown()


def test_worker_restart_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor = WorkerPoolSupervisor()
    restarted: list[bool] = []

    def mock_start_worker(cls: type[BaseWorkerProcess], i: int) -> None:
        restarted.append(True)

    monkeypatch.setattr(supervisor, "_start_worker", mock_start_worker)

    class DeadWorker:
        def is_alive(self) -> bool:
            return False

        def join(self, timeout: Optional[float] = None) -> None:
            return

        exitcode: int = 1
        pid: int = 42

    _parent_conn, child_conn = Pipe()
    for cls in supervisor.processes:
        supervisor.processes[cls][0] = DeadWorker()  # type: ignore
        supervisor.heartbeat_conns[cls][0] = child_conn

    supervisor._is_worker_dead = lambda p, c, a, b: True  # type: ignore
    supervisor._shutdown.clear()

    supervisor._start_heartbeat_monitor()
    time.sleep(2)

    assert restarted
    supervisor.shutdown()


def test_restart_debounce_logic() -> None:
    supervisor = WorkerPoolSupervisor()

    for cls in supervisor.processes:
        supervisor._last_restart[cls][0] = time.monotonic()  # recent restart
        # Try to start worker; should be skipped
        supervisor._start_worker(cls, 0)
        # Assert that no new process was created
        assert supervisor.processes[cls][0] is None
    supervisor.shutdown()


def test_worker_stuck_no_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    supervisor = WorkerPoolSupervisor()
    restarted = False

    class SilentProc:
        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            pass

        def join(self, timeout: Optional[float] = None) -> None:
            pass

        def kill(self) -> None:
            pass

        exitcode: None = None
        pid: int = 111

    def mock_start_worker(cls: type[BaseWorkerProcess], i: int) -> None:
        nonlocal restarted
        restarted = True

    monkeypatch.setattr(supervisor, "_start_worker", mock_start_worker)

    for cls in supervisor.processes:
        supervisor.processes[cls][0] = SilentProc()  # type: ignore
        parent_conn, _child_conn = Pipe()
        supervisor.heartbeat_conns[cls][0] = parent_conn

    supervisor._start_heartbeat_monitor()
    time.sleep(2)

    assert restarted
    supervisor.shutdown()
