from typing import TYPE_CHECKING, cast

from supabase import create_client

from backend.env_loader import EnvLoader

if TYPE_CHECKING:
    from backend.stubs.supabase import AsyncSupabaseClient


class SupabaseManager:
    def __init__(self) -> None:
        self.client: AsyncSupabaseClient = cast(
            "AsyncSupabaseClient",
            create_client(
                EnvLoader.get("SUPABASE_URL"),
                EnvLoader.get("SUPABASE_SERVICE_ROLE_KEY"),
            ),
        )
