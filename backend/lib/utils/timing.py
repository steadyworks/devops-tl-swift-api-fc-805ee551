import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from uuid import UUID


@asynccontextmanager
async def log_timing(
    step_name: str, photobook_id: Optional[UUID] = None, worker_id: Optional[int] = None
) -> AsyncGenerator[None, None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        prefix = f"[worker: {worker_id}][job {photobook_id}] " if photobook_id else ""
        logging.info(f"{prefix}[timing] {step_name}: {duration:.3f} sec")
