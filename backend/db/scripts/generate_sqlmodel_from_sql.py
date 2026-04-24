"""
Usage:
cd $(git rev-parse --show-toplevel)/backend && PYTHONPATH=.. python db/scripts/generate_sqlmodel_from_sql.py

This script parses the schema.sql file and generates SQLModel classes into backend/db/data_models/__init__.py
"""

import re
import subprocess
from pathlib import Path
from typing import Any

OUTPUT_FILE = Path("db/data_models/__init__.py")
INPUT_FILE = Path("db/schema.sql")

SQL_TO_PYTHON_TYPE: dict[str, str] = {
    "boolean": "bool",
    "uuid": "UUID",
    "text": "str",
    "character varying": "str",
    "jsonb": "dict[str, Any]",
    "integer": "int",
    "timestamp without time zone": "datetime",
    "timestamp with time zone": "datetime",
    "timestamp": "datetime",  # fallback
    "inet": "str",
}

RESERVED_NAMES = {"metadata"}
ENUMS: dict[str, list[str]] = {}  # SQL enum name → list of values


def snake_to_pascal_case(s: str) -> str:
    return "".join(word.capitalize() for word in s.split("_"))


def parse_enums(sql: str) -> None:
    matches = re.findall(
        r"CREATE TYPE (?:public\.)?(\w+) AS ENUM\s*\((.*?)\);",
        sql,
        re.DOTALL | re.IGNORECASE,
    )
    for enum_name, values_raw in matches:
        values = [v.strip().strip("'") for v in values_raw.split(",")]
        ENUMS[enum_name] = values


def parse_tables(
    sql: str, alter_pk_constraints: dict[str, set[str]]
) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    primary_keys_per_table: dict[str, set[str]] = {}
    table_blocks = re.findall(
        r"CREATE TABLE public\.(\w+)\s*\((.*?)\);", sql, re.DOTALL
    )

    for table_name, body in table_blocks:
        columns: list[dict[str, Any]] = []
        lines = [
            line.strip().rstrip(",")
            for line in body.strip().splitlines()
            if line.strip()
            and not line.strip().startswith("--")
            and not re.match(
                r"(?i)(CHECK|CONSTRAINT|PRIMARY KEY|UNIQUE|FOREIGN KEY)", line.strip()
            )
        ]

        # Find PRIMARY KEY (col1, col2) line
        primary_key_line = next(
            (line for line in lines if line.upper().startswith("PRIMARY KEY")),
            None,
        )
        if primary_key_line:
            pk_cols_raw = re.search(r"\((.*?)\)", primary_key_line)
            if pk_cols_raw:
                primary_keys_per_table[table_name] = set(
                    col.strip() for col in pk_cols_raw.group(1).split(",")
                )

        for line in lines:
            parts = line.split()
            if not parts:
                continue

            col_name = parts[0].strip('"')
            raw_type = " ".join(parts[1:]).strip()

            nullable = "NOT NULL" not in raw_type.upper()
            default = None

            default_match = re.search(r"DEFAULT\s+([^ ]+)", raw_type, re.IGNORECASE)
            if default_match:
                default = default_match.group(1).strip().rstrip(",")

            # Now strip DEFAULT and NOT NULL from raw_type so we don't double-parse them
            raw_type = re.sub(
                r"DEFAULT\s+[^ ]+", "", raw_type, flags=re.IGNORECASE
            ).strip()
            raw_type = re.sub(r"NOT NULL", "", raw_type, flags=re.IGNORECASE).strip()

            col: dict[str, Any] = {
                "name": col_name,
                "type": raw_type.strip(),
                "nullable": nullable,
                "default": default,
            }
            columns.append(col)
        for col in columns:
            col["is_primary"] = col["name"] in primary_keys_per_table.get(
                table_name, set()
            )
        tables[table_name] = columns

    # Handle ALTER TABLE statements for primary keys
    for table_name, pk_cols in alter_pk_constraints.items():
        if table_name not in tables:
            continue
        for col in tables[table_name]:
            if col["name"] in pk_cols:
                col["is_primary"] = True

    return tables


def extract_base_type(raw_type: str) -> str:
    raw_type = raw_type.lower()
    raw_type = re.split(r"\bdefault\b", raw_type)[0].strip()
    raw_type = re.split(r"\bnot null\b", raw_type)[0].strip()
    raw_type = re.split(r"\bnull\b", raw_type)[0].strip()
    raw_type = raw_type.split("::")[0].strip()

    # Handle public.schema prefix like 'public.user_provided_occasion'
    if raw_type.startswith("public."):
        raw_type = raw_type.split(".", 1)[1]
    return raw_type


def map_column_to_field(col: dict[str, Any]) -> str:
    orig_name = col["name"]
    nullable = col["nullable"]
    is_reserved = orig_name in RESERVED_NAMES
    name = orig_name + "_" if is_reserved else orig_name

    sql_type = extract_base_type(col["type"])
    is_primary = col.get("is_primary", False)
    default = col.get("default")

    # Infer Python type
    if sql_type in ENUMS:
        py_type = snake_to_pascal_case(sql_type)
        sa_column_expr = (
            f'sa_column=Column(Enum({py_type}, name="{sql_type}", native_enum=True, '
            f"nullable={'True' if nullable else 'False'}, values_callable=enum_values))"
        )
    else:
        py_type = SQL_TO_PYTHON_TYPE.get(sql_type, "Any")
        sa_column_expr = None

    # Wrap in Optional[...] if nullable and not primary key
    type_prefix = f"Optional[{py_type}]" if nullable and not is_primary else py_type

    field_args: list[str] = []

    # Primary key handling
    if is_primary:
        field_args.append("primary_key=True")
        if default and "gen_random_uuid()" in default:
            field_args.append("default_factory=uuid4")

    # Default handling
    elif default:
        normalized_default = default.strip("'").strip('"').lower()

        if "now()" in default:
            field_args.append("default_factory=lambda: datetime.now(timezone.utc)")
        elif re.match(r"^\d+$", default):  # numeric
            field_args.append(f"default={default}")
        elif normalized_default in {"null", "none"}:
            field_args.append("default=None")
        elif sql_type == "boolean":
            if normalized_default in {"false", "false::boolean"}:
                field_args.append("default=False")
            elif normalized_default in {"true", "true::boolean"}:
                field_args.append("default=True")
            else:
                field_args.append(f"default={repr(default)}")
        elif sql_type in ENUMS:
            if normalized_default in ENUMS[sql_type]:
                enum_class = snake_to_pascal_case(sql_type)
                enum_const = normalized_default.upper().replace(" ", "_")
                field_args.append(f"default={enum_class}.{enum_const}")
        else:
            field_args.append(f"default={repr(normalized_default)}")

    # If nullable with no default, make it explicit
    elif nullable:
        field_args.append("default=None")

    # Only apply nullable=... when no sa_column
    if not sa_column_expr:
        field_args.append(f"nullable={'True' if nullable else 'False'}")

    # JSON type hint
    if sql_type in {"json", "jsonb"}:
        field_args.append("sa_type=JSON")

    if is_reserved:
        raise Exception(
            "Naming a field metadata is known to cause problems with SQLAlchemy. Please rename the column."
        )

    if sa_column_expr:
        field_args.append(sa_column_expr)

    field_expr = f" = Field({', '.join(field_args)})" if field_args else ""
    return f"    {name}: {type_prefix}{field_expr}"


def render_enum(name: str, values: list[str]) -> str:
    enum_name = snake_to_pascal_case(name)
    lines = [f"class {enum_name}(str, enum.Enum):"]
    for value in values:
        const_name = value.upper().replace(" ", "_")
        lines.append(f"    {const_name} = {repr(value)}")
    return "\n".join(lines)


def render_model(table_name: str, columns: list[dict[str, Any]]) -> str:
    class_name = "".join(word.capitalize() for word in table_name.split("_"))
    lines = [f"class DAO{class_name}(SQLModel, table=True):"]
    lines.append(f'    __tablename__ = cast("Any", "{table_name}")')
    if not columns:
        lines.append("    pass")
    else:
        lines += [map_column_to_field(col) for col in columns]
    return "\n".join(lines)


def main() -> None:
    sql = INPUT_FILE.read_text()

    # Step 1: Parse enums and tables
    parse_enums(sql)
    alter_pk_constraints = parse_alter_primary_keys(sql)
    tables = parse_tables(sql, alter_pk_constraints)

    # Step 2: Emit header
    generated_header = """# ---------------------------------------------
# ⚠️ AUTO-GENERATED FILE — DO NOT EDIT MANUALLY
# Source: backend/db/schemas/__init__.py, backend/db/data_models/__init__.py
# Generated by: backend/db/scripts/generate_sqlmodel_from_sql.py
# ---------------------------------------------

"""

    header_imports = """import enum
from datetime import datetime, timezone
from typing import Any, Optional, cast
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import JSON
from sqlmodel import Field, SQLModel, Column, Enum

def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    \"\"\"Get values for enum.\"\"\"
    return [status.value for status in enum_class]


"""

    # Step 3: Emit body
    enum_block = "\n\n".join(
        render_enum(name, values) for name, values in ENUMS.items()
    )
    model_block = "\n\n".join(
        render_model(name, cols)
        for name, cols in tables.items()
        if name != "schema_migrations"
    )

    # Step 4: Write file
    OUTPUT_FILE.write_text(
        generated_header + header_imports + enum_block + "\n\n" + model_block + "\n"
    )
    print(f"✅ Generated {OUTPUT_FILE}")

    # Step 5: Run Ruff
    try:
        subprocess.run(["ruff", "format", OUTPUT_FILE], check=True)
        subprocess.run(
            ["ruff", "check", "--select", "I", "--fix", OUTPUT_FILE],
            check=True,
        )
        print("✅ Applied ruff formatting")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ruff formatting failed: {e}")
    except FileNotFoundError:
        print("⚠️ Ruff not installed. Run `pip install ruff`.")


def parse_alter_primary_keys(sql: str) -> dict[str, set[str]]:
    """
    Parse ALTER TABLE statements to find primary key constraints.
    """
    primary_keys: dict[str, set[str]] = {}
    matches = re.findall(
        r"ALTER TABLE ONLY public\.(\w+)\s+ADD CONSTRAINT \w+ PRIMARY KEY\s*\((.*?)\);",
        sql,
        flags=re.IGNORECASE,
    )
    for table_name, pk_cols_raw in matches:
        cols = [col.strip() for col in pk_cols_raw.split(",")]
        primary_keys.setdefault(table_name, set()).update(cols)
    return primary_keys


if __name__ == "__main__":
    main()
