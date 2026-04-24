import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, Self, TypeVar, Union

from redis.asyncio import Connection, ConnectionPool, StrictRedis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend.env_loader import EnvLoader

FieldT = str | int | float | bytes

LOCAL_DEFAULT_HOST = "localhost"
LOCAL_DEFAULT_PORT = 6379
ReturnT = TypeVar("ReturnT")


_REDIS_SOFT_ERRORS: tuple[type[Exception], ...] = (
    ConnectionError,
    RedisTimeoutError,
)


class SafeRedisClient:
    def __init__(
        self, client: "StrictRedis[str]", factory: "RedisClientFactory"
    ) -> None:
        self._client = client
        self._factory = factory

    async def _soft_reset_idle(self) -> None:
        pool = self._client.connection_pool
        if pool is not None:
            await pool.disconnect(inuse_connections=False)

    async def _exec(self, op: Callable[[], Awaitable[ReturnT]]) -> ReturnT:
        try:
            return await op()
        except _REDIS_SOFT_ERRORS as first:
            logging.warning("[redis] Redis hiccup: %s -- pruning idle sockets", first)
            await self._soft_reset_idle()
            await asyncio.sleep(random.uniform(0.05, 0.15))
            try:
                return await op()
            except _REDIS_SOFT_ERRORS as second:
                logging.error("[redis] Retry failed: %s", second)
                raise

    async def safe_blpop(
        self, key: str, timeout: Union[int, float]
    ) -> Optional[tuple[str, str]]:
        return await self._exec(lambda: self._client.blpop(key, timeout=timeout))

    async def safe_rpush(self, name: str, *values: FieldT) -> int:
        return await self._exec(lambda: self._client.rpush(name, *values))

    async def _safe_close_underlying_client(self) -> None:
        try:
            await self._client.close(close_connection_pool=False)
        except Exception as close_err:
            logging.warning(f"[redis] Error while closing Redis client: {close_err}")

    async def close(self) -> None:
        await self._safe_close_underlying_client()


class RedisClientFactory:
    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        socket_timeout: int,
        socket_connect_timeout: int,
        health_check_interval: int,
        socket_keepalive: bool,
        retry_strategy: Retry,
        max_connections: int,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._health_check_interval = health_check_interval
        self._socket_keepalive = socket_keepalive
        self._retry_strategy = retry_strategy
        logging.info(
            f"[redis factory] Creating redis client pool, host={host}, "
            f"max_connections={max_connections}"
        )
        self._connection_pool: "ConnectionPool[Connection]" = ConnectionPool(
            host=host,
            port=port,
            username=username,
            password=password,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            socket_keepalive=socket_keepalive,
            decode_responses=True,
            max_connections=max_connections,
        )

    @classmethod
    def from_remote_defaults(cls) -> Self:
        return cls(
            host=EnvLoader.get("REDIS_HOST"),
            port=int(EnvLoader.get("REDIS_PORT")),
            username=EnvLoader.get("REDIS_USERNAME"),
            password=EnvLoader.get("REDIS_PASSWORD"),
            socket_timeout=20,
            socket_connect_timeout=10,
            health_check_interval=20,
            socket_keepalive=True,
            retry_strategy=Retry(
                backoff=ExponentialBackoff(),
                retries=3,
                supported_errors=(ConnectionError, RedisTimeoutError),
            ),
            max_connections=15,
        )

    @classmethod
    def from_local_defaults(cls) -> Self:
        return cls(
            host=LOCAL_DEFAULT_HOST,
            port=LOCAL_DEFAULT_PORT,
            username=None,
            password=None,
            socket_timeout=10,
            socket_connect_timeout=2,
            health_check_interval=0,
            socket_keepalive=False,
            retry_strategy=Retry(
                backoff=ExponentialBackoff(),
                retries=2,
                supported_errors=(ConnectionError, RedisTimeoutError),
            ),
            max_connections=10,
        )

    def new_raw_redis_client_INTERNAL_ONLY_DO_NOT_USE(self) -> "StrictRedis[str]":
        """Internal helper: creates a new Redis client using the shared pool."""
        return StrictRedis(
            connection_pool=self._connection_pool,
            retry=self._retry_strategy,
            decode_responses=True,
        )

    def new_redis_client(self) -> SafeRedisClient:
        logging.info("[redis factory] Creating new redis client")
        return SafeRedisClient(
            client=self.new_raw_redis_client_INTERNAL_ONLY_DO_NOT_USE(), factory=self
        )

    async def close_pool(self) -> None:
        """Gracefully disconnects the shared connection pool."""
        await self._connection_pool.disconnect()
