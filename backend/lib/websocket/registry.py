from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, ClassVar

from fastapi import WebSocket

if TYPE_CHECKING:
    from uuid import UUID


logger = logging.getLogger(__name__)


class WebSocketRegistry:
    _user_sockets: ClassVar[dict[UUID, set[WebSocket]]] = defaultdict(set)
    _registry_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    @classmethod
    async def register(cls, user_id: UUID, socket: WebSocket) -> None:
        async with cls._registry_lock:
            cls._user_sockets[user_id].add(socket)
        logger.debug(f"[WSRegistry] Registered socket for user {user_id}")

    @classmethod
    async def unregister(cls, user_id: UUID, socket: WebSocket) -> None:
        async with cls._registry_lock:
            sockets = cls._user_sockets.get(user_id)
            if sockets is not None:
                sockets.discard(socket)
                if not sockets:
                    cls._user_sockets.pop(user_id, None)
        logger.debug(f"[WSRegistry] Unregistered socket for user {user_id}")

    @classmethod
    async def close_all(cls) -> None:
        async with cls._registry_lock:
            sockets_by_user = list(cls._user_sockets.items())
            cls._user_sockets.clear()

        for user_id, sockets in sockets_by_user:
            for socket in sockets:
                try:
                    await socket.close()
                except Exception as e:
                    logger.error(
                        f"[WSRegistry] Error closing socket for user {user_id}: {e}"
                    )
