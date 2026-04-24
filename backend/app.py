# Configure logging environment
import logging
import signal
from contextlib import asynccontextmanager
from types import FrameType
from typing import TYPE_CHECKING, AsyncGenerator, Awaitable, Callable, Optional

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import compile_path

from backend.db.session.factory import AsyncSessionFactory
from backend.env_loader import EnvLoader
from backend.lib.asset_manager.factory import AssetManagerFactory
from backend.lib.job_manager.base import JobManager
from backend.lib.job_manager.types import JobQueue
from backend.lib.redis.factory import RedisClientFactory, SafeRedisClient
from backend.lib.request.context import RequestContext
from backend.path_manager import PathManager
from backend.route_handler.asset import AssetAPIHandler
from backend.route_handler.base import RouteHandler
from backend.route_handler.dev import DevAPIHandler
from backend.route_handler.page import PageAPIHandler
from backend.route_handler.photobook import PhotobookAPIHandler
from backend.route_handler.share import ShareAPIHandler
from backend.route_handler.user import UserAPIHandler

from .openapi_override import custom_openapi  # type: ignore[attr-defined]

if TYPE_CHECKING:
    from backend.lib.asset_manager.base import AssetManager

from .logging_utils import configure_logging_env

configure_logging_env()


def _on_sighup(sig: int, frame: Optional[FrameType]) -> None:
    logging.info("🔁 HUP received. Reloading env...")
    EnvLoader.reload_env()
    logging.info("🔁 Reloaded env vars.")


signal.signal(signal.SIGHUP, _on_sighup)

sentry_sdk.init(
    dsn=EnvLoader.get("SENTRY_DSN"),
    send_default_pii=True,
    environment=EnvLoader.get("SENTRY_ENVIRONMENT", "development"),
)


class TimelensApp:
    ENABLED_ROUTE_HANDLERS_CLS: list[type[RouteHandler]] = [
        PhotobookAPIHandler,
        PageAPIHandler,
        AssetAPIHandler,
        UserAPIHandler,
        ShareAPIHandler,
    ]
    ENABLED_ROUTE_HANDLERS_CLS_DEV_ONLY: list[type[RouteHandler]] = [DevAPIHandler]

    def __init__(self) -> None:
        # Thread safe resources, safe to share
        self.path_manager = PathManager()
        self.asset_manager: AssetManager = AssetManagerFactory().create()

        # Thread safe objects
        self._local_redis_factory: RedisClientFactory = (
            RedisClientFactory.from_local_defaults()
        )
        self._remote_redis_factory: RedisClientFactory = (
            RedisClientFactory.from_remote_defaults()
        )
        self._local_redis_client: SafeRedisClient = (
            self._local_redis_factory.new_redis_client()
        )
        self._remote_redis_client: SafeRedisClient = (
            self._remote_redis_factory.new_redis_client()
        )
        self.local_job_manager = JobManager(
            self._local_redis_client, JobQueue.LOCAL_MAIN_TASK_QUEUE_CPU_BOUND
        )
        self.remote_job_manager_io_bound = JobManager(
            self._remote_redis_client, JobQueue.REMOTE_MAIN_TASK_QUEUE_IO_BOUND
        )
        self.remote_job_manager_cpu_bound = JobManager(
            self._remote_redis_client,
            JobQueue.REMOTE_MAIN_TASK_QUEUE_CPU_BOUND,
        )

        # Thread unsafe underlying resources, one resource per request, shared factory
        self.db_session_factory = AsyncSessionFactory()

        # Patch iOS safe datetime render
        self.app: FastAPI = FastAPI(lifespan=self.lifespan)

        # Patch self.app with custom OpenAPI wrapper compatible with iOS
        setattr(self.app, "openapi", lambda: custom_openapi(app))

        self.app.middleware("http")(self._attach_request_context)

        for route_handler_cls in TimelensApp.ENABLED_ROUTE_HANDLERS_CLS:
            self.app.include_router(route_handler_cls(self).get_router())

        if EnvLoader.is_development():
            for route_handler_cls in TimelensApp.ENABLED_ROUTE_HANDLERS_CLS_DEV_ONLY:
                self.app.include_router(route_handler_cls(self).get_router())
            self.app.mount(
                "/assets",
                StaticFiles(directory=PathManager().get_assets_root()),
                name="assets",
            )

            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=[
                    "http://127.0.0.1:3000",
                    "http://localhost:3000",
                ],
                allow_credentials=True,
                allow_methods=["*"],  # or restrict to ["GET", "POST", "PUT", ...]
                allow_headers=["*"],
            )

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        logging.info("Server initializing...")
        logging.info("Server initialize complete...")
        yield
        logging.info("Server cleaning up...")
        await self._local_redis_client.close()
        await self._remote_redis_client.close()
        await self._local_redis_factory.close_pool()
        await self._remote_redis_factory.close_pool()
        await self.db_session_factory.engine().dispose()
        logging.info("Server cleanup complete...")

    @asynccontextmanager
    async def new_db_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.db_session_factory.new_session() as session:
            yield session

    @classmethod
    def matches_unauthenticated_path(cls, request_path: str) -> bool:
        for route_pattern in RouteHandler.unauthenticated_routes:
            path_regex, _, _ = compile_path(route_pattern)
            if path_regex.match(request_path):
                return True
        return False

    async def _attach_request_context(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Skip authentication for these paths
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        if self.matches_unauthenticated_path(request.url.path.rstrip("/")):
            return await call_next(request)

        if EnvLoader.is_development() and EnvLoader.is_debug_bypass_auth_enabled():
            return await call_next(request)

        async with self.new_db_session() as db_session:
            try:
                await RequestContext.from_request(request, db_session=db_session)
            except HTTPException as e:
                return JSONResponse(
                    status_code=e.status_code, content={"detail": e.detail}
                )
            return await call_next(request)

    async def get_request_context(self, request: Request) -> RequestContext:
        # If already cached by middleware, return it
        if hasattr(request.state, "ctx"):
            return request.state.ctx

        # Else, open a short-lived session just for user lookup
        async with self.db_session_factory.new_session() as session:
            return await RequestContext.from_request(request, db_session=session)


timelens_app = TimelensApp()
app = timelens_app.app
