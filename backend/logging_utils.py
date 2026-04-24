import logging
import time
from collections import deque

from .env_loader import EnvLoader


# ────────────────────────────────
# Rate-limit filter ─ keeps at most `max_records`
# identical log entries per `interval_secs` seconds
# ────────────────────────────────
class RateLimitFilter(logging.Filter):
    def __init__(self, *, max_records: int = 5, interval_secs: float = 60.0) -> None:
        super().__init__()
        self.max_records = max_records
        self.interval = interval_secs
        # (logger name, level, message) → timestamps
        self._history: dict[tuple[str, int, str], deque[float]] = {}

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        key = (record.name, record.levelno, record.getMessage())
        now = time.time()

        dq = self._history.setdefault(key, deque())
        # drop timestamps that are outside the window
        while dq and now - dq[0] > self.interval:
            dq.popleft()

        if len(dq) < self.max_records:
            dq.append(now)
            return True  # keep the record
        return False  # discard – too many duplicates


def configure_logging_env() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clean slate
    while root_logger.hasHandlers():
        root_logger.removeHandler(root_logger.handlers[0])

    # Decide format based on env
    if EnvLoader.is_production():
        log_fmt = "%(asctime)s [%(levelname)s] %(message)s"
        level = logging.INFO
    else:
        log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        level = logging.INFO

    formatter = logging.Formatter(log_fmt)
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # ────────────────────────────────
    # Install rate-limiting filter
    #   – tweak max_records / interval_secs as you wish
    # ────────────────────────────────
    root_logger.addFilter(RateLimitFilter(max_records=5, interval_secs=60))

    # (Optional) turn down very chatty third-party loggers
    # logging.getLogger("redis").setLevel(logging.ERROR)
    # logging.getLogger("aioredis").setLevel(logging.ERROR)
