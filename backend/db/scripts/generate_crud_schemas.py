"""
Usage:
cd $(git rev-parse --show-toplevel)/backend && PYTHONPATH=.. python db/scripts/generate_crud_schemas.py
"""

import ast
import subprocess
from datetime import datetime as _DT
from typing import Any, Optional, Union, get_args, get_origin

from sqlmodel import SQLModel

import backend.db.data_models as data_models

# Path to the output file
OUTPUT_PATH = "db/dal/schemas.py"
OUTPUT_PATH_EXTERNALS = "db/externals/_generated_DO_NOT_USE.py"
INIT_PATH_EXTERNALS = "db/externals/__init__.py"
OVERRIDES_PATH = "db/externals/_overrides.py"

# Track types used for imports
used_typenames: set[str] = set()
EXCLUDED_MODELS = {"SchemaMigrations"}


def is_optional_type(tp: Any) -> bool:
    """Return True if the type is Optional[...]"""
    return get_origin(tp) is Union and type(None) in get_args(tp)


def get_typename_read(t: Any) -> str:
    """Like get_typename, but map datetime → ISO8601UTCDateTime for Readable models only."""
    origin = get_origin(t)
    args = get_args(t)

    # Optional[datetime] or Union[…, datetime, None]
    if origin is Union and args:
        # Rebuild the union with datetime swapped to ISO8601UTCDateTime
        parts: list[str] = []
        for a in args:
            if a is type(None):
                parts.append("None")
            elif a is _DT:
                used_typenames.add("ISO8601UTCDateTime")
                parts.append("ISO8601UTCDateTime")
            else:
                parts.append(get_typename_read(a))
        # Collapse Optional[T] shape if it’s just T|None
        non_none = [p for p in parts if p != "None"]
        if len(non_none) == 1 and len(parts) == 2:
            used_typenames.add("Optional")
            return f"Optional[{non_none[0]}]"
        return " | ".join(parts)

    # Plain datetime
    if t is _DT:
        used_typenames.add("ISO8601UTCDateTime")
        return "ISO8601UTCDateTime"

    # Fallback to default behavior
    return get_typename(t)


def generate_crud_schemas(
    model_cls: type[SQLModel], name: str
) -> tuple[str, str, bool]:
    fields: dict[str, Any] = model_cls.model_fields
    create_fields: dict[str, tuple[Any, Any, dict[str, Any]]] = {}
    read_fields: dict[str, tuple[type[Any], Any, dict[str, Any]]] = {}
    update_fields: dict[str, tuple[Any, Any, dict[str, Any]]] = {}

    used_field = False

    for fname, f in fields.items():
        annotation: Any = f.annotation
        field_info: dict[str, Any] = {}
        if f.alias and f.alias != fname:
            field_info["alias"] = f.alias

        if fname in {"created_at"}:
            read_fields[fname] = (annotation, ..., field_info)
        elif fname in {"id"}:
            read_fields[fname] = (annotation, ..., field_info)
            create_fields[fname] = (
                Optional[annotation],
                None,
                {"default_factory": "uuid4"},
            )  # allows explicitly passing ID
        elif fname in {"updated_at"}:
            update_fields[fname] = (Optional[annotation], None, field_info)
            read_fields[fname] = (annotation, ..., field_info)
        else:
            create_fields[fname] = (annotation, ..., field_info)
            update_fields[fname] = (Optional[annotation], None, field_info)
            read_fields[fname] = (annotation, ..., field_info)

    def render_field(
        name: str,
        typ: Any,
        default: Any,
        info: dict[str, Any],
        *,
        force_default_none: bool = False,
        read_mode: bool = False,
    ) -> str:
        nonlocal used_field
        typename = get_typename_read(typ) if read_mode else get_typename(typ)

        if info:
            used_field = True
            args = ", ".join(
                f"{k}={v}" if k == "default_factory" else f"{k}={repr(v)}"
                for k, v in info.items()
            )

            if default is ... and not force_default_none:
                return f"    {name}: {typename} = Field({args})"

            if "default_factory" in info:
                return f"    {name}: {typename} = Field(default_factory=uuid4)"
            return (
                f"    {name}: {typename} = Field(default=None, {args})"
                if force_default_none
                else f"    {name}: {typename} = Field(default={default}, {args})"
            )

        if default is ... and not force_default_none:
            return f"    {name}: {typename}"
        return (
            f"    {name}: {typename} = None"
            if force_default_none
            else f"    {name}: {typename} = {repr(default)}"
        )

    lines: list[str] = []

    lines.append(f"class {name}Create(WritableModel):")
    if create_fields:
        for k, (typ, default, info) in create_fields.items():
            force_default_none = is_optional_type(typ)
            lines.append(
                render_field(
                    k, typ, default, info, force_default_none=force_default_none
                )
            )
    else:
        lines.append("    pass")
    lines.append("")

    lines.append(f"class {name}Update(WritableModel):")
    if update_fields:
        for k, (typ, default, info) in update_fields.items():
            lines.append(render_field(k, typ, default, info))
    else:
        lines.append("    pass")
    lines.append("")

    lines_public: list[str] = []
    lines_public.append(
        f"class _{name.removeprefix('DAO')}OverviewResponse(APIResponseModel[{name}]):"
    )
    if read_fields:
        for k, (typ, default, info) in read_fields.items():
            lines_public.append(render_field(k, typ, default, info, read_mode=True))
    else:
        lines_public.append("    pass")
    lines_public.append("")

    return "\n".join(lines), "\n".join(lines_public), used_field


def get_typename(t: Any) -> str:
    origin = get_origin(t)
    args = get_args(t)

    if origin is Union and args:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            used_typenames.add("Optional")
            return f"Optional[{get_typename(non_none_args[0])}]"
        return " | ".join(get_typename(a) for a in args)

    if origin is list and args:
        used_typenames.add("list")
        return f"list[{get_typename(args[0])}]"

    if origin is dict and len(args) == 2:
        used_typenames.add("dict")
        return f"dict[{get_typename(args[0])}, {get_typename(args[1])}]"

    # ENUM FIX: track all used explicit type names (like UserProvidedOccasion)
    type_name = getattr(t, "__name__", str(t))
    used_typenames.add(type_name)
    return type_name


def emit_imports(
    field_used: bool, model_cls_set: set[type[SQLModel]]
) -> tuple[str, str]:
    lines: list[str] = [
        "from pydantic import BaseModel, ConfigDict",
    ]
    if field_used:
        lines.append("from sqlmodel import Field ")

    if "Optional" in used_typenames:
        lines.append("from typing import Optional")
    if "Any" in used_typenames:
        lines.append("from typing import Any")
    if "UUID" in used_typenames:
        lines.append("from uuid import UUID, uuid4")
    if "datetime" in used_typenames:
        lines.append("from datetime import datetime")

    # Import enums used in type hints
    enum_types = [
        tname
        for tname in sorted(used_typenames)
        if tname
        not in {
            "Optional",
            "Any",
            "UUID",
            "datetime",
            "list",
            "dict",
            "str",
            "int",
            "bool",
        }
    ]
    if enum_types:
        lines.append(
            f"from backend.db.data_models import {', '.join(t for t in enum_types if t != 'ISO8601UTCDateTime')}"
        )

    readable_extra = f"""\n
from sqlmodel import SQLModel
from typing import TypeVar, Generic, Self, Protocol, Sequence, runtime_checkable, Any, Annotated
from backend.db.data_models import {", ".join(model_cls.__name__ for model_cls in model_cls_set)}
from pydantic import BaseModel, field_serializer, PlainSerializer, WithJsonSchema
from datetime import datetime, timezone

TDAO = TypeVar("TDAO", bound=SQLModel, contravariant=True)

# ---- Datetime type alias for READABLE models only ----
def _dt_seconds_z(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.isoformat(timespec="seconds").replace("+00:00", "Z")

ISO8601UTCDateTime = Annotated[
    datetime,
    PlainSerializer(_dt_seconds_z, return_type=str, when_used="json"),
    WithJsonSchema({{"type": "string", "format": "date-time"}}),
]
# ------------------------------------------------------

class APIResponseModelConvertibleFromDAOMixin(BaseModel, Generic[TDAO]):
    @classmethod
    def from_dao(cls, dao: TDAO) -> Self:
        dao_dict = dao.model_dump()
        allowed_keys = cls.model_fields.keys()
        filtered = {{k: v for k, v in dao_dict.items() if k in allowed_keys}}
        return cls.model_validate(filtered)
        
    @classmethod
    def from_daos(cls, daos: Sequence[TDAO]) -> list[Self]:
        return [cls.from_dao(dao) for dao in daos]


class APIResponseModel(BaseModel, Generic[TDAO]):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

@runtime_checkable
class CanBeBatchRenderedFromDAOs(Protocol, Generic[TDAO]):
    @classmethod
    async def rendered_from_daos(
        cls: type[Self], dao: Sequence[TDAO], *args: Any, **kwargs: Any
    ) -> Sequence[Self]: ...

"""

    writeable_extra = """\n
class WritableModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)  # used for Create/Update"""

    return (
        "\n".join(lines) + readable_extra + "\n\n",
        "\n".join(lines) + writeable_extra + "\n\n",
    )


if __name__ == "__main__":
    all_cls: list[tuple[type[SQLModel], str]] = []
    for name, cls in vars(data_models).items():
        if (
            isinstance(cls, type)
            and issubclass(cls, SQLModel)
            and name not in EXCLUDED_MODELS
            and cls.__name__ != "SQLModel"
        ):
            all_cls.append((cls, name))

    used_typenames.clear()
    class_defs: list[str] = []
    class_defs_read: list[str] = []
    field_used = False
    model_cls_set: set[type[SQLModel]] = set()

    for model_cls, name in all_cls:
        class_def, class_def_read, model_uses_field = generate_crud_schemas(
            model_cls, name
        )
        class_defs.append(class_def)
        class_defs_read.append(class_def_read)
        field_used |= model_uses_field
        model_cls_set.add(model_cls)

    imports_read, imports_write = emit_imports(field_used, model_cls_set)

    header = """# ---------------------------------------------
# ⚠️ AUTO-GENERATED FILE — DO NOT EDIT MANUALLY
# Source: backend/db/data_models/__init__.py
# Generated by: backend/db/scripts/generate_crud_schemas.py
# ---------------------------------------------

"""

    content = header + imports_write + "\n".join(class_defs)
    with open(OUTPUT_PATH, "w") as f:
        f.write(content)
    print(f"✅ Wrote: {OUTPUT_PATH}")

    header_read = """# ---------------------------------------------
# ⚠️ AUTO-GENERATED FILE — DO NOT EDIT MANUALLY
# Source: backend/db/data_models/__init__.py
# Generated by: backend/db/scripts/generate_crud_schemas.py
# ---------------------------------------------
# pyright: reportPrivateUsage=false
# pyright: reportUnusedClass=false
# pyright: reportUnusedImport=false
# ruff: noqa: F401

"""
    content_read = header_read + imports_read + "\n".join(class_defs_read)
    with open(OUTPUT_PATH_EXTERNALS, "w") as f:
        f.write(content_read)
    print(f"✅ Wrote: {OUTPUT_PATH_EXTERNALS}")

    class_names = [name.removeprefix("DAO") + "OverviewResponse" for _, name in all_cls]
    class_names_sorted = sorted(class_names)

    overridden_classes: set[str] = set()

    try:
        with open(OVERRIDES_PATH, "r") as f:
            tree = ast.parse(f.read(), filename=OVERRIDES_PATH)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    overridden_classes.add(node.name)
    except FileNotFoundError:
        # No _overrides.py — ignore
        pass

    init_header = '''# ---------------------------------------------
# ⚠️ AUTO-GENERATED FILE — DO NOT EDIT MANUALLY
# Source: backend/db/data_models/__init__.py
# Generated by: backend/db/scripts/generate_crud_schemas.py
# ---------------------------------------------
# pyright: reportPrivateUsage=false
# pyright: reportUnusedClass=false
# pyright: reportUnusedImport=false
# ruff: noqa: F401

"""
This __init__.py exposes public OverviewResponse classes.

- If a class is overridden in _overrides.py, we use that.
- Otherwise, fall back to _generated_DO_NOT_USE.py.
"""

'''

    # Emit __all__ declaration
    import_lines = [
        "from ._generated_DO_NOT_USE import (",
        "    APIResponseModelConvertibleFromDAOMixin,",
        *[f"    _{name}," for name in class_names_sorted],
        ")",
        "",
    ]

    import_lines += [
        "from backend.db.data_models import (",
        *[f"    {name}," for _, name in all_cls if name != "ISO8601UTCDateTime"],
        ")",
        "",
    ]

    # Add static imports for overridden ones
    for name in class_names_sorted:
        if name in overridden_classes:
            import_lines.append(f"from ._overrides import {name}  # noqa: E402")
        else:
            import_lines.append(
                f"""class {name}(_{name}, APIResponseModelConvertibleFromDAOMixin[{"DAO" + name.removesuffix("OverviewResponse")}]):
    pass"""
            )

    all_export = f"__all__ = {class_names_sorted!r}\n"
    init_content = init_header + "\n".join(import_lines) + "\n\n" + all_export
    with open(INIT_PATH_EXTERNALS, "w") as f:
        f.write(init_content)

    print(f"✅ Wrote: {INIT_PATH_EXTERNALS}")

    # Run Ruff format
    try:
        subprocess.run(["ruff", "format", OUTPUT_PATH], check=True)
        subprocess.run(
            ["ruff", "check", "--select", "I", "--fix", OUTPUT_PATH], check=True
        )
        subprocess.run(["ruff", "format", OUTPUT_PATH_EXTERNALS], check=True)
        subprocess.run(
            ["ruff", "check", "--select", "I", "--fix", OUTPUT_PATH_EXTERNALS],
            check=True,
        )
        subprocess.run(["ruff", "format", INIT_PATH_EXTERNALS], check=True)
        subprocess.run(
            ["ruff", "check", "--select", "I", "--fix", INIT_PATH_EXTERNALS],
            check=True,
        )
        print("✅ Applied ruff formatting")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ruff formatting failed: {e}")
    except FileNotFoundError:
        print("⚠️ Ruff not installed. Run `pip install ruff`.")
