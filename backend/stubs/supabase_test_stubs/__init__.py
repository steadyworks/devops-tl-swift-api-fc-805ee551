from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.stubs.supabase import (
    APIResponse,
    AsyncQueryRequestBuilder,
    AsyncSupabaseClient,
    AsyncSupabaseTable,
)


class APIResponseStub(APIResponse[Any]):
    def __init__(self, data: Any, error: Any = None):
        self.data = data
        self.error = error


class QueryBuilderStub(AsyncQueryRequestBuilder[Any]):
    def __init__(self, table: "TableStub"):
        self._table = table
        self._filter: Optional[tuple[str, Any]] = None
        self._update_data: Optional[Dict[str, Any]] = None
        self._single = False
        self._select = True  # For now we always select "*"

    def insert(self, json: Dict[str, Any]) -> "QueryBuilderStub":
        now = datetime.now(timezone.utc).isoformat()

        default_fields: Dict[str, Any] = {
            "id": str(uuid4()),
            "created_at": now,
            "updated_at": now,
            "status": "draft",  # optional: may override based on model
            "result_payload": None,
            "error_message": None,
            "started_at": None,
            "completed_at": None,
        }

        self._new_row = {**default_fields, **json}
        self._table.rows.append(self._new_row)
        return self

    def update(self, json: Dict[str, Any]) -> "QueryBuilderStub":
        self._update_data = json
        return self

    def select(self, *columns: str) -> "QueryBuilderStub":
        return self

    def eq(self, column: str, value: Any) -> "QueryBuilderStub":
        self._filter = (column, value)
        return self

    def order(self, column: str, desc: bool = False) -> "QueryBuilderStub":
        return self  # You can enhance this if needed

    def single(self) -> "QueryBuilderStub":
        self._single = True
        return self

    async def execute(self) -> APIResponse[Any]:
        rows = self._table.rows

        if hasattr(self, "_new_row"):  # Handle insert
            return APIResponseStub(data=[self._new_row])

        if self._filter:
            key, val = self._filter
            rows = [row for row in rows if str(row.get(key)) == str(val)]

        if self._update_data:
            for row in rows:
                row.update(self._update_data)

        if self._single:
            if rows:
                return APIResponseStub(data=rows[0])
            return APIResponseStub(data=None, error="Not found")

        return APIResponseStub(data=rows)


class TableStub(AsyncSupabaseTable[Any]):
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows

    def insert(self, json: Dict[str, Any]) -> QueryBuilderStub:
        return QueryBuilderStub(self).insert(json)

    def update(self, json: Dict[str, Any]) -> QueryBuilderStub:
        return QueryBuilderStub(self).update(json)

    def select(self, *columns: str) -> QueryBuilderStub:
        return QueryBuilderStub(self)

    def eq(self, column: str, value: Any) -> QueryBuilderStub:
        return QueryBuilderStub(self).eq(column, value)

    def single(self) -> QueryBuilderStub:
        return QueryBuilderStub(self).single()

    def order(self, column: str, desc: bool = False) -> QueryBuilderStub:
        return QueryBuilderStub(self)


class SupabaseClientStub(AsyncSupabaseClient):
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows

    def table(self, name: str) -> TableStub:
        return TableStub(self._rows)

    def get_rows(self) -> List[Dict[str, Any]]:
        return self._rows
