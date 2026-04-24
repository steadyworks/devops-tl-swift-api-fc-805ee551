from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

# Import your types/adapters
# (Adjust these imports to match your module structure)
from .types import (
    ClientToServerAdapter,
    ClientToServerMessage,
    ServerToClientAdapter,
    ServerToClientMessage,
)

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Raised when an incoming frame fails schema validation or is malformed."""


class WebSocketCodec:
    """
    Minimal send/recv codec around a starlette WebSocket using Pydantic TypeAdapters.
    - recv(): receive one validated ClientToServerMessage
    - send(): send one validated ServerToClientMessage
    - aiter_recv(): async iterator yielding validated messages until disconnect
    """

    def __init__(
        self,
        websocket: WebSocket,
        *,
        client_adapter: TypeAdapter[ClientToServerMessage] = ClientToServerAdapter,
        server_adapter: TypeAdapter[ServerToClientMessage] = ServerToClientAdapter,
    ) -> None:
        self.ws = websocket
        self._client_adapter = client_adapter
        self._server_adapter = server_adapter

    # ---- Receive ----
    async def recv(self, *, timeout: float | None = None) -> ClientToServerMessage:
        """
        Receive a single JSON frame and validate as ClientToServerMessage.
        Raises:
          - WebSocketDisconnect if socket closed
          - ProtocolError on schema/format errors
        """
        try:
            if timeout is None:
                # Use receive_json() for speed + less parsing boilerplate
                raw = await self.ws.receive_json()
            else:
                raw = await asyncio.wait_for(self.ws.receive_json(), timeout=timeout)
        except WebSocketDisconnect:
            raise
        except asyncio.TimeoutError as e:
            raise ProtocolError("receive timeout") from e
        except Exception as e:
            # Could be non-JSON or other framing error
            raise ProtocolError(f"invalid JSON frame: {e}") from e

        try:
            return self._client_adapter.validate_python(raw)
        except ValidationError as e:
            raise ProtocolError(f"schema validation failed: {e}") from e

    async def aiter_recv(
        self, *, log_prefix: str = "", keepalive: bool = False
    ) -> AsyncIterator[ClientToServerMessage]:
        """
        Async iterator over incoming messages until disconnect.
        If keepalive=True, silently ignore ProtocolError frames and continue.
        """
        while True:
            try:
                msg = await self.recv()
            except WebSocketDisconnect:
                if log_prefix:
                    logger.info("%s WebSocket disconnected", log_prefix)
                break
            except ProtocolError as e:
                if log_prefix:
                    logger.warning("%s Protocol error: %s", log_prefix, e)
                if keepalive:
                    continue
                else:
                    break
            except Exception as e:
                if log_prefix:
                    logger.exception("%s Unexpected recv error: %s", log_prefix, e)
                break

            yield msg

    # ---- Send ----
    async def send(self, message: ServerToClientMessage) -> None:
        """
        Validate & send a ServerToClientMessage as JSON.
        """
        try:
            # Ensure correct shape; returns plain dict suitable for send_json
            payload = self._server_adapter.dump_python(message, mode="json")
            await self.ws.send_json(payload)
        except WebSocketDisconnect:
            raise
        except Exception as e:
            # (We don't re-validate here; dump_python already checks the variant shape)
            logger.warning("send failed: %s", e)
            raise
