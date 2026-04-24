from fastapi import Request, Response

from backend.path_manager import PathManager
from backend.route_handler.base import RouteHandler, unauthenticated_route


class DevAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.router.add_api_route(
            "/api/dev/asset_upload/{key:path}",
            self.dev_asset_upload_put,
            methods=["PUT"],
            response_model=None,
        )

    @unauthenticated_route
    async def dev_asset_upload_put(
        self, key: str, request: Request
    ) -> Response:
        dest_path = PathManager().get_assets_root() / key
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with dest_path.open("wb") as f:
            async for chunk in request.stream():
                f.write(chunk)

        return Response(status_code=200)
