from typing import TYPE_CHECKING, Any, Callable, ParamSpec, TypeVar, get_type_hints
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.dal import (
    DALPages,
    DALPhotobooks,
    DAOPhotobooks,
)
from backend.db.data_models import DAOPages
from backend.lib.request.context import RequestContext
from backend.lib.utils.common import none_throws

if TYPE_CHECKING:
    from backend.app import TimelensApp  # Avoids circular import


T = TypeVar("T", bound=Callable[..., Any])
_response_model_registry: dict[Callable[..., Any], type[Any]] = {}


P = ParamSpec("P")
R = TypeVar("R")


def unauthenticated_route(func: Callable[P, R]) -> Callable[P, R]:
    setattr(func, "_allow_unauthenticated", True)
    return func


def enforce_response_model(func: T) -> T:
    hints = get_type_hints(func)
    return_type = hints.get("return")
    if return_type is None:
        raise ValueError(f"{func.__name__} must have a return type annotation")

    # Normalize to underlying function (unbound)
    key = getattr(func, "__func__", func)
    _response_model_registry[key] = return_type
    return func


def get_response_model(func: Callable[..., Any]) -> type[Any]:
    # Normalize to underlying function (unbound)
    key = getattr(func, "__func__", func)
    return _response_model_registry[key]


class RouteHandler:
    unauthenticated_routes: set[str] = set()

    def __init__(self, app: "TimelensApp") -> None:
        self.app = app
        self.router = APIRouter()
        self.register_routes()

    def register_routes(self) -> None:
        pass

    def get_router(self) -> APIRouter:
        return self.router

    async def get_request_context(self, request: Request) -> RequestContext:
        return await self.app.get_request_context(request)

    def route(self, path: str, method_name: str, methods: list[str]) -> None:
        # Retrieve method
        if not hasattr(self, method_name):
            raise RuntimeError(
                f"Method {method_name} not found on handler class {self.__class__.__name__}"
            )

        method = getattr(self, method_name)

        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} on {self.__class__.__name__} is not callable"
            )

        try:
            response_model = get_response_model(method)
        except KeyError:
            raise RuntimeError(
                f"Method {method_name} is not decorated with @enforce_response_model"
            )

        self.router.add_api_route(
            path,
            method,
            methods=methods,
            response_model=response_model,
        )

        if getattr(method, "_allow_unauthenticated", False):
            RouteHandler.unauthenticated_routes.add(path)

    def websocket_route(self, path: str, method_name: str) -> None:
        # Retrieve method
        if not hasattr(self, method_name):
            raise RuntimeError(
                f"WebSocket method {method_name} not found on handler class {self.__class__.__name__}"
            )

        method = getattr(self, method_name)

        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} on {self.__class__.__name__} is not callable"
            )

        self.router.add_api_websocket_route(path, method)

        if getattr(method, "_allow_unauthenticated", False):
            RouteHandler.unauthenticated_routes.add(path)

    async def get_page_assert_owned_by(
        self,
        db_session: AsyncSession,
        page_id: UUID,
        owner_id: UUID,
    ) -> DAOPages:
        page = await DALPages.get_by_id(db_session, page_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Page not found")

        photobook = await DALPhotobooks.get_by_id(
            db_session, none_throws(page.photobook_id)
        )
        if not photobook or photobook.owner_id != owner_id:
            raise HTTPException(
                status_code=403, detail="Not authorized to edit this page"
            )

        return page

    async def get_photobook_assert_owned_by(
        self,
        db_session: AsyncSession,
        photobook_id: UUID,
        owner_id: UUID,
    ) -> DAOPhotobooks:
        photobook = await DALPhotobooks.get_by_id(db_session, photobook_id)
        if photobook is None:
            raise HTTPException(status_code=404, detail="Page not found")
        if photobook.owner_id != owner_id:
            raise HTTPException(
                status_code=403, detail="Not authorized to edit this page"
            )

        return photobook
