from enum import Enum


class JobQueue(Enum):
    # Local queues (same host)
    LOCAL_MAIN_TASK_QUEUE_CPU_BOUND = "local_main_task_queue_cpu_bound"

    # Remote queues (global)
    REMOTE_MAIN_TASK_QUEUE_IO_BOUND = "remote_main_task_queue_io_bound"
    REMOTE_MAIN_TASK_QUEUE_CPU_BOUND = "remote_main_task_queue_cpu_bound"
