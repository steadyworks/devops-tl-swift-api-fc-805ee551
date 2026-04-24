import socket
from datetime import datetime, timezone
from typing import Optional, TypeVar

T = TypeVar("T")


def none_throws(value: Optional[T], message: str = "Value cannot be None") -> T:
    if value is None:
        raise Exception(message)
    return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_host_info() -> str:
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    return f"{hostname}, {ip_address}"
