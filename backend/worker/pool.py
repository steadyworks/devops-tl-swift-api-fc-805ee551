import logging
import multiprocessing as mp
import signal
import sys
import threading
import time
from multiprocessing import Process
from multiprocessing.connection import Connection
from typing import Any, Optional

from backend.logging_utils import configure_logging_env
from backend.worker.process.base import (
    READY_SIGNAL_MSG,
    SHUTDOWN_SIGNAL_MSG,
    BaseWorkerProcess,
)
from backend.worker.process.remote_cpu_bound import RemoteJobCPUBoundWorkerProcess
from backend.worker.process.remote_io_bound import RemoteJobIOBoundWorkerProcess

# [(worker_type_cls, num_processes)]
WORKER_PROCESS_CONFIGS: list[tuple[type[BaseWorkerProcess], int]] = [
    (RemoteJobIOBoundWorkerProcess, 1),
    (RemoteJobCPUBoundWorkerProcess, 2),
]
PROCESS_RESTART_PACEOUT_SECS = 60
HEARTBEAT_TIMEOUT_SECS = 10
STARTUP_GRACE_SECS = 30


class WorkerPoolSupervisor:
    def __init__(self) -> None:
        self.processes: dict[type[BaseWorkerProcess], list[Optional[mp.Process]]] = {
            worker_process_cls: [None] * num_workers
            for (worker_process_cls, num_workers) in WORKER_PROCESS_CONFIGS
        }
        self.heartbeat_conns: dict[
            type[BaseWorkerProcess], list[Optional[Connection]]
        ] = {
            worker_process_cls: [None] * num_workers
            for (worker_process_cls, num_workers) in WORKER_PROCESS_CONFIGS
        }
        self._last_restart: dict[type[BaseWorkerProcess], list[float]] = {
            cls: [0.0] * n for cls, n in WORKER_PROCESS_CONFIGS
        }
        self._last_heartbeat: dict[type[BaseWorkerProcess], list[float]] = {
            cls: [time.monotonic()] * n for cls, n in WORKER_PROCESS_CONFIGS
        }

        self._shutdown = threading.Event()

    def start(self) -> None:
        self._start_all_workers()
        time.sleep(2)  #  Add delay to let workers initialize
        self._start_heartbeat_monitor()

    def _start_worker(
        self, worker_process_cls: type[BaseWorkerProcess], i: int
    ) -> None:
        assert (
            worker_process_cls in self.processes
            and worker_process_cls in self.heartbeat_conns
        )
        now = time.monotonic()

        processes = self.processes[worker_process_cls]
        heartbeat_conns = self.heartbeat_conns[worker_process_cls]

        # Clean up old process
        old_proc = processes[i]
        if old_proc is not None:
            logging.info(
                f"Cleaning up old process: {worker_process_cls.__name__}-{i}"
                f", pid: {old_proc.pid}"
            )
            if old_proc.is_alive():
                old_proc.terminate()
            old_proc.join(timeout=1)
            if old_proc.is_alive():
                old_proc.kill()
                old_proc.join()

        # Clean up old heartbeat pipe
        old_conn = heartbeat_conns[i]
        if old_conn:
            try:
                old_conn.close()
            except Exception:
                pass

        if self._shutdown.is_set():
            logging.info(
                "[Pool] Shutdown in progress. "
                f"Skipping worker {worker_process_cls.__name__}-{i} restart"
            )
            return

        # Check for last restart
        last_restart = self._last_restart[worker_process_cls][i]
        if now - last_restart < PROCESS_RESTART_PACEOUT_SECS:
            logging.warning(
                f"[Pool] Worker {worker_process_cls.__name__}-{i} restarted too recently. Skipping restart."
            )
            return

        # Start new worker
        parent_conn, child_conn = mp.Pipe(duplex=True)
        p = worker_process_cls(
            child_conn, name=f"worker-{worker_process_cls.__name__}-{i}"
        )

        # Do not set daemon=True so process can shut down gracefully and allow joining
        p.daemon = False

        try:
            p.start()
        except Exception as e:
            logging.exception(
                f"start() failed for {worker_process_cls.__name__}-{i}: {e}"
            )
            # still record attempt so we don't hammer
            self._last_restart[worker_process_cls][i] = time.monotonic()
            return

        self._last_restart[worker_process_cls][i] = now

        # --- READY handshake ------------------------------------------------------
        if parent_conn.poll(STARTUP_GRACE_SECS):
            try:
                msg = parent_conn.recv()
            except EOFError:
                logging.error(
                    f"[Pool] Pipe closed before READY from {worker_process_cls.__name__}-{i}"
                )
                p.terminate()
                p.join()
                return
            if msg != READY_SIGNAL_MSG:
                logging.error(f"[Pool] Unexpected first message from worker: {msg!r}")
                p.terminate()
                p.join()
                return
        else:
            logging.error(
                f"[Pool] {worker_process_cls.__name__}-{i} failed to send READY within {STARTUP_GRACE_SECS}s"
            )
            p.terminate()
            p.join()
            return

        if not p.is_alive():
            logging.exception(
                f"Worker {worker_process_cls.__name__}-{i} failed to start"
            )
            p.join()
            return

        self.processes[worker_process_cls][i] = p
        self.heartbeat_conns[worker_process_cls][i] = parent_conn
        logging.info(
            f"[Pool] Started worker {worker_process_cls.__name__}-{i} with PID {p.pid}"
        )

    def _start_all_workers(self) -> None:
        for worker_process_cls, num_workers in WORKER_PROCESS_CONFIGS:
            for i in range(num_workers):
                self._start_worker(worker_process_cls, i)

    def _is_worker_dead(
        self,
        p: Optional[Process],
        conn: Optional[Connection],
        worker_cls: type[BaseWorkerProcess],
        slot_idx: int,
    ) -> bool:
        if p is None:
            logging.info(f"_is_worker_dead, p is None: {p}")
            return True
        if not p.is_alive() or p.exitcode is not None:
            logging.info(
                f"_is_worker_dead, p.is_alive(): {p.is_alive()}, p.exitcode: {p.exitcode}"
            )
            return True
        if conn is None:
            logging.info(f"_is_worker_dead, p: {p}, conn is None")
            return True

        if conn.poll(0):
            try:
                _ = conn.recv()
                self._last_heartbeat[worker_cls][slot_idx] = time.monotonic()
                return False
            except Exception as e:
                logging.warning(f"Heartbeat pipe error: {e}")
                return True

        time_monotonic = time.monotonic()
        if (
            time_monotonic - self._last_heartbeat[worker_cls][slot_idx]
            > HEARTBEAT_TIMEOUT_SECS
        ):
            logging.info(
                f"_is_worker_dead, p: {p}, time_monotonic: {time_monotonic}, "
                f"last_hearbeat: {self._last_heartbeat[worker_cls][slot_idx]}"
            )
            return True
        return False

    def _start_heartbeat_monitor(self) -> None:
        def monitor_and_restart_workers() -> None:
            while not self._shutdown.is_set():
                for worker_process_cls, num_workers in WORKER_PROCESS_CONFIGS:
                    for i in range(num_workers):
                        if self._shutdown.is_set():
                            break

                        p = self.processes[worker_process_cls][i]
                        conn = self.heartbeat_conns[worker_process_cls][i]
                        dead = self._is_worker_dead(p, conn, worker_process_cls, i)

                        if dead and not self._shutdown.is_set():
                            logging.info(
                                f"[Pool] Worker {i} is dead or unresponsive "
                                f"(PID={None if p is None else p.pid}). Restarting..."
                            )
                            self._start_worker(worker_process_cls, i)

                time.sleep(1)

        threading.Thread(target=monitor_and_restart_workers, daemon=True).start()

    def shutdown(self) -> None:
        self._shutdown.set()

        # 🔁 Tell each worker to shut down via the pipe
        for worker_process_cls, _num_workers in WORKER_PROCESS_CONFIGS:
            for i, (p, conn) in enumerate(
                zip(
                    self.processes[worker_process_cls],
                    self.heartbeat_conns[worker_process_cls],
                )
            ):
                if p is None:
                    continue

                try:
                    if conn is not None and not conn.closed:
                        conn.send(SHUTDOWN_SIGNAL_MSG)
                except Exception as e:
                    logging.warning(
                        "[Pool] Failed to send shutdown to worker"
                        f"{worker_process_cls.__name__}-{i}: {e}"
                    )

        # 🔁 Join all processes
        for worker_process_cls, _num_workers in WORKER_PROCESS_CONFIGS:
            for i, p in enumerate(self.processes[worker_process_cls]):
                if p is None:
                    continue
                logging.info(f"[Pool] Joining process: {p.pid}")
                p.join(timeout=2)
                if p.is_alive():
                    logging.warning(
                        f"[Pool] Process {worker_process_cls.__name__}-{i}, "
                        f"pid: {p.pid} did not exit in time, terminating..."
                    )
                    p.terminate()
                    p.join(timeout=2)
                    if p.is_alive():
                        p.kill()
                        p.join()


def main() -> None:
    configure_logging_env()

    pool = WorkerPoolSupervisor()
    pool.start()

    def handle_signal(sig: int, frame: Any) -> None:
        logging.info(f"Received signal {sig}, shutting down gracefully...")
        pool.shutdown()
        time.sleep(1)  # let logs flush
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Wait for signal in main thread
    threading.Event().wait()


if __name__ == "__main__":
    main()
