import json
import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Generic, Optional, TypeVar
from typing import cast as typing_cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    and_,
    asc,
    case,
    cast,
    delete,
    desc,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy import exists as sa_exists
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Column as SAColumn
from sqlmodel import SQLModel

from backend.db.dal.schemas import WritableModel
from backend.lib.types.exception import UUIDNotFoundError
from backend.lib.utils.common import utcnow

SQLModelType = TypeVar("SQLModelType", bound=SQLModel)


@asynccontextmanager
async def safe_commit(
    session: AsyncSession,
    context: Optional[str] = None,
    raise_on_fail: bool = True,
) -> AsyncGenerator[None, None]:
    """
    Context manager for safely committing a DB session.

    Usage:
        async with safe_commit(session, context="photobook status update"):
            await do_some_db_ops()

    Args:
        session: SQLAlchemy AsyncSession
        context: Optional string describing what is being committed (for logging)
        raise_on_fail: If False, exceptions are logged but not re-raised
    """
    log_context: str = f" during {context}" if context else ""
    try:
        yield  # user code executes here
        try:
            await session.commit()
        except Exception as commit_exc:
            await session.rollback()
            logging.exception(
                f"[DB] Commit failed: {log_context}. Rolled back. Exception: {commit_exc}"
            )
            if raise_on_fail:
                raise
    except Exception as block_exc:
        await session.rollback()
        log_context = f" during {context}" if context else ""
        logging.exception(
            f"[DB] Error inside DB block {log_context}. Rolled back. Exception: {block_exc}"
        )
        if raise_on_fail:
            raise


@asynccontextmanager
async def safe_transaction(
    session: AsyncSession,
    context: Optional[str] = None,
    raise_on_fail: bool = True,
) -> AsyncGenerator[None, None]:
    """
    Context manager that guarantees a new SQLAlchemy transaction using session.begin().
    It raises an error if a transaction is already in progress.

    Args:
        session: SQLAlchemy AsyncSession
        context: Optional description for logging
        raise_on_fail: Whether to re-raise on failure
    """
    log_context = f" during {context}" if context else ""

    if session.in_transaction():
        raise RuntimeError(
            f"[DB] Cannot use safe_transaction while a transaction is already active{log_context}."
        )

    try:
        async with session.begin():
            yield
    except Exception as e:
        logging.exception(
            f"[DB] Transaction failed{log_context}. Rolled back. Exception: {e}"
        )
        if raise_on_fail:
            raise


@asynccontextmanager
async def locked_row_by_id(
    session: AsyncSession,
    model: type[SQLModelType],
    id: UUID,
) -> AsyncGenerator[SQLModelType, None]:
    """
    Acquire a row-level FOR UPDATE lock on a single SQLModel row by its primary key.
    Yields the ORM object if found, else raises UUIDNotFoundError.
    """
    stmt = select(model).where(model.id == id).with_for_update()  # type: ignore[attr-defined] # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType, reportAttributeAccessIssue]
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        logging.warning(
            f"[DB] locked_row_by_id: no {model.__name__} found with id={id}"
        )
        raise UUIDNotFoundError(id)
    try:
        yield row
    finally:
        # lock is released when the transaction/session ends
        pass


class FilterOp(str, Enum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    IN = "in"
    NOT_IN = "not_in"


class OrderDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


# === TypeVars ===

ModelType = TypeVar("ModelType", bound=SQLModel)

CreateSchemaType = TypeVar("CreateSchemaType", bound=WritableModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=WritableModel)


# === Exceptions ===


class InvalidFilterFieldError(ValueError):
    def __init__(self, field: str, model: type[SQLModel]) -> None:
        super().__init__(f"Invalid field '{field}' for model '{model.__name__}'")


# === DAL ===
class AsyncPostgreSQLDAL(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    model: type[ModelType]  # Must be set in subclass
    IMMUTABLE_FIELDS: set[str] = {"id", "created_at"}
    AUTO_UPDATE_FIELDS: dict[str, Callable[[], Any]] = {"updated_at": lambda: utcnow()}

    @classmethod
    def _get_column(cls, field: str) -> Any:
        if not hasattr(cls.model, field):
            raise InvalidFilterFieldError(field, cls.model)
        return getattr(cls.model, field)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: UUID) -> Optional[ModelType]:
        return await session.get(cls.model, id)

    @classmethod
    async def get_by_ids(
        cls, session: AsyncSession, ids: list[UUID]
    ) -> list[ModelType]:
        if not ids:
            return []
        id_col = getattr(cls.model, "id")
        stmt = select(cls.model).where(id_col.in_(ids))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def create(cls, session: AsyncSession, obj_in: CreateSchemaType) -> ModelType:
        db_obj: ModelType = cls.model.model_validate(obj_in)
        session.add(db_obj)
        await session.flush()
        return db_obj

    @classmethod
    async def update_many_by_ids(
        cls,
        session: AsyncSession,
        updates: dict[UUID, Any],  # update schema type
    ) -> None:
        """
        Batch update rows using per-ID update schema objects.

        Args:
            session: Active DB session.
            updates: Mapping of UUID -> partial update object.
        """
        if not updates:
            logging.info("update_many_by_id called with empty dict. Skipping.")
            return

        try:
            id_col = getattr(cls.model, "id")

            parsed_updates: list[tuple[UUID, dict[str, Any]]] = []
            for id_, update_obj in updates.items():
                data = update_obj.model_dump(exclude_unset=True)
                if not data:
                    continue
                parsed_updates.append((id_, data))

            if not parsed_updates:
                logging.info("No fields to update after parsing. Skipping.")
                return

            all_fields: set[str] = set()
            for _, data in parsed_updates:
                all_fields.update(data.keys())

            if not all_fields:
                logging.warning("No fields detected for update.")
                return

            # Map field name -> Enum SQLAlchemy type (for explicit cast)
            column_map: dict[str, Optional[PgEnum]] = {}
            for field in all_fields:
                column: Optional[SAColumn[Any]] = cls.model.__table__.columns.get(field)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]

                if column is None:
                    continue
                if isinstance(column.type, PgEnum):  # pyright: ignore[reportUnknownMemberType]
                    column_map[field] = column.type
                else:
                    column_map[field] = None

            values_to_set: dict[str, Any] = {}
            for field in all_fields:
                enum_type = column_map.get(field)
                field_cases: dict[UUID, Any] = {}
                for id_, data in parsed_updates:
                    if field not in data:
                        continue
                    value = data[field]
                    if value is None:
                        continue

                    if enum_type:
                        field_cases[id_] = cast(value, enum_type)
                    elif isinstance(value, dict):
                        field_cases[id_] = literal(
                            typing_cast("dict[str, Any]", json.dumps(value))
                        ).cast(JSONB)
                    else:
                        field_cases[id_] = value

                values_to_set[field] = case(field_cases, value=id_col)

            stmt = (
                update(cls.model)
                .where(id_col.in_([id_ for id_, _ in parsed_updates]))
                .values(**values_to_set)
            )

            await session.execute(stmt)

        except Exception:
            logging.exception("update_many_by_id failed.")
            raise

    @classmethod
    async def update_by_id(
        cls, session: AsyncSession, id: UUID, obj_in: UpdateSchemaType
    ) -> ModelType:
        db_obj: ModelType | None = await session.get(cls.model, id)
        if db_obj is None:
            raise UUIDNotFoundError(id)
        return await cls._update(session, db_obj, obj_in)

    @classmethod
    async def _update(
        cls, session: AsyncSession, db_obj: ModelType, obj_in: UpdateSchemaType
    ) -> ModelType:
        update_data: dict[str, Any] = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field not in cls.IMMUTABLE_FIELDS and hasattr(db_obj, field):
                setattr(db_obj, field, value)

        for field, factory in cls.AUTO_UPDATE_FIELDS.items():
            if not hasattr(
                db_obj, field
            ):  # Data model does not contain auto update field
                continue

            if (
                hasattr(obj_in, field) and getattr(obj_in, field) is not None
            ):  # Explicit value set by update request
                continue

            setattr(db_obj, field, factory())

        session.add(db_obj)
        await session.flush()
        return db_obj

    @classmethod
    def _resolve_filter_condition(
        cls,
        field: str,
        op: FilterOp,
        value: Any,
    ) -> ColumnElement[bool]:
        column = cls._get_column(field)
        if op == FilterOp.EQ:
            return column == value
        if op == FilterOp.NE:
            return column != value
        if op == FilterOp.LT:
            return column < value
        if op == FilterOp.LTE:
            return column <= value
        if op == FilterOp.GT:
            return column > value
        if op == FilterOp.GTE:
            return column >= value
        if op == FilterOp.IN and isinstance(value, list):
            return column.in_(value)
        if op == FilterOp.NOT_IN and isinstance(value, list):
            return column.not_in(value)
        raise ValueError(f"Unsupported filter op: {op}")

    @classmethod
    def _build_filter_conditions(
        cls,
        filters: Optional[dict[str, tuple[FilterOp, Any]]],
    ) -> list[ColumnElement[bool]]:
        if not filters:
            return []
        return [
            cls._resolve_filter_condition(f, op, v) for f, (op, v) in filters.items()
        ]

    @classmethod
    async def list_all(
        cls,
        session: AsyncSession,
        filters: Optional[dict[str, tuple[FilterOp, Any]]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by: Optional[list[tuple[str, OrderDirection]]] = None,
    ) -> list[ModelType]:
        stmt = select(cls.model)

        conditions = cls._build_filter_conditions(filters)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        if order_by:
            stmt = stmt.order_by(
                *[
                    (
                        desc(cls._get_column(field))
                        if direction == OrderDirection.DESC
                        else asc(cls._get_column(field))
                    )
                    for field, direction in order_by
                ]
            )

        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def count(
        cls,
        session: AsyncSession,
        filters: Optional[dict[str, tuple[FilterOp, Any]]] = None,
    ) -> int:
        stmt = select(func.count()).select_from(cls.model)
        conditions = cls._build_filter_conditions(filters)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await session.execute(stmt)
        return result.scalar_one()

    @classmethod
    async def exists(
        cls,
        session: AsyncSession,
        filters: Optional[dict[str, tuple[FilterOp, Any]]] = None,
    ) -> bool:
        conditions = cls._build_filter_conditions(filters)
        stmt = (
            select(sa_exists().where(and_(*conditions)))
            if conditions
            else select(sa_exists().select_from(cls.model))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is True

    @classmethod
    async def create_many(
        cls,
        session: AsyncSession,
        objs_in: list[CreateSchemaType],
    ) -> list[ModelType]:
        """
        Bulk-insert a list of CreateSchemaType in one SQL statement,
        returning the newly-created ORM objects with DB defaults applied.
        """
        if not objs_in:
            return []

        # 1) Convert Pydantic/WritableModel inputs into plain dicts
        payloads = [obj.model_dump() for obj in objs_in]

        # 2) Build and execute a single INSERT ... RETURNING * statement
        stmt = insert(cls.model).returning(cls.model)
        result = await session.execute(stmt, payloads)

        # 3) Extract ORM objects
        new_objs: list[ModelType] = list(result.scalars().all())

        # 4) Attach them to the session so further operations see them
        for obj in new_objs:
            session.add(obj)

        # 5) Flush to generate any remaining defaults/PKs
        await session.flush()
        return new_objs

    @classmethod
    async def delete_by_id(
        cls,
        session: AsyncSession,
        id: UUID,
    ) -> None:
        """
        Hard-delete a row by ID. Raises UUIDNotFoundError if not found.

        Args:
            session: Active DB session.
            id: UUID of the row to delete.
        """
        try:
            obj = await session.get(cls.model, id)
            if obj is None:
                raise UUIDNotFoundError(id)

            await session.delete(obj)
            await session.flush()
        except UUIDNotFoundError:
            raise
        except Exception:
            logging.exception(
                f"Failed to hard delete {cls.model.__name__} with ID: {id}"
            )
            raise

    @classmethod
    async def delete_many_by_ids(
        cls,
        session: AsyncSession,
        ids: list[UUID],
    ) -> int:
        """
        Hard-delete multiple rows by their primary keys.
        Raises UUIDNotFoundError if any requested ID does not exist.
        Returns the total number of rows deleted.
        """
        if not ids:
            logging.info("delete_by_ids called with empty list. Skipping.")
            return 0

        id_col = getattr(cls.model, "id")

        # 1) verify all exist
        stmt = select(id_col).where(id_col.in_(ids))
        result = await session.execute(stmt)
        existing = {row[0] for row in result.all()}
        missing = set(ids) - existing
        if missing:
            missing_id = next(iter(missing))
            logging.warning(
                f"[DB] delete_by_ids: no {cls.model.__name__} found for id={missing_id}"
            )
            raise UUIDNotFoundError(missing_id)

        # 2) bulk delete
        delete_stmt = (
            delete(cls.model)
            .where(id_col.in_(ids))
            .execution_options(synchronize_session="fetch")
        )
        res = await session.execute(delete_stmt)
        # keep ORM session in sync
        await session.flush()

        return res.rowcount or 0
