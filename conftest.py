"""Root-level conftest for devops_tl tasks.

Runs at pytest collection start (before any test module imports). Responsibilities:

  1. Bring up postgres (`pg_ctlcluster 16 main start`).
  2. Bring up redis (`redis-server --daemonize yes`).
  3. Ensure role `photobook` and database `photobook` exist.
  4. Stub `auth.users` for FK satisfaction (matches timelens-prod's Supabase setup).
  5. Run `dbmate up` to apply all migrations present in db/migrations/.
  6. Optionally regenerate db/data_models + db/dal/schemas if the harness
     vendored codegen scripts are present AND the current data_models/
     directory is not already populated (i.e. the agent ships only SQL).

All network-external services (Stripe, Twilio, RevenueCat, etc.) are NOT
started — tasks selected for the devops_tl track must not require them.

If you are authoring a new devops_tl task and its tests fail with an
external-service network error, the commit was a poor candidate — revisit
the filter criteria.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_APP = Path("/app")
_BACKEND = _APP / "backend"
_MIGRATIONS = _BACKEND / "db" / "migrations"
_DATA_MODELS = _BACKEND / "db" / "data_models"
_DB_SCRIPTS = _BACKEND / "db" / "scripts"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://photobook:photobook@localhost:5432/photobook?sslmode=disable",
)
SUPERUSER_URL = "postgres://postgres@localhost:5432/postgres?sslmode=disable"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Some backend/tests/conftest.py fixtures (pg_engine, etc.) skip when
# TEST_DATABASE_URL is unset. Point at a DEDICATED empty DB —
# pg_engine runs SQLModel.drop_all/create_all and conflicts with dbmate
# migration tables if pointed at the main DB. Use psycopg3 async driver
# (asyncpg isn't in requirements.txt).
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://photobook:photobook@localhost:5432/photobook_test",
)


def _log(msg: str) -> None:
    sys.stderr.write(f"[root-conftest] {msg}\n")


# -- postgres --------------------------------------------------------------


def _start_postgres() -> None:
    if subprocess.run(["pg_isready", "-U", "postgres"], capture_output=True).returncode == 0:
        return
    subprocess.run(["pg_ctlcluster", "16", "main", "start"], check=False)
    for _ in range(60):
        if subprocess.run(["pg_isready", "-U", "postgres"], capture_output=True).returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("postgres did not become ready within 30s")


def _ensure_role_and_db() -> None:
    import psycopg
    with psycopg.connect(SUPERUSER_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'photobook'")
        if cur.fetchone() is None:
            cur.execute(
                "CREATE ROLE photobook WITH LOGIN SUPERUSER PASSWORD 'photobook'"
            )
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'photobook'")
        if cur.fetchone() is None:
            cur.execute("CREATE DATABASE photobook OWNER photobook")
        # Separate DB for backend/tests/conftest.py's pg_engine fixture — it
        # runs SQLModel.metadata.drop_all/create_all and expects a DB it owns
        # fully (not co-inhabited by dbmate migration tables with external FKs).
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'photobook_test'")
        if cur.fetchone() is None:
            cur.execute("CREATE DATABASE photobook_test OWNER photobook")


def _ensure_auth_stub() -> None:
    """Mirror timelens prod: auth.users exists (Supabase), public is ours.

    Wipe public on every pytest run to give tests a deterministic starting DB.
    """
    import psycopg
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO photobook")
        cur.execute("GRANT ALL ON SCHEMA public TO public")
        cur.execute("DROP SCHEMA IF EXISTS auth CASCADE")
        cur.execute("CREATE SCHEMA auth")
        cur.execute("GRANT USAGE ON SCHEMA auth TO photobook")
        cur.execute(
            "CREATE TABLE auth.users ("
            "  id uuid PRIMARY KEY,"
            "  email text, phone text,"
            "  email_confirmed_at timestamptz,"
            "  phone_confirmed_at timestamptz,"
            "  raw_user_meta_data jsonb,"
            "  created_at timestamptz,"
            "  updated_at timestamptz,"
            "  confirmed_at timestamptz,"
            "  banned_until timestamptz,"
            "  deleted_at timestamptz,"
            "  is_anonymous boolean NOT NULL DEFAULT false"
            ")"
        )
        cur.execute("GRANT ALL ON auth.users TO photobook")


# -- redis -----------------------------------------------------------------


def _start_redis() -> None:
    # Best-effort. If a test imports nothing redis-related, this is harmless.
    try:
        r = subprocess.run(["redis-cli", "ping"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and "PONG" in r.stdout:
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    subprocess.run(["redis-server", "--daemonize", "yes"], check=False)
    for _ in range(20):
        try:
            r = subprocess.run(["redis-cli", "ping"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and "PONG" in r.stdout:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.25)
    _log("warning: redis did not become ready; tests that need it will fail")


# -- dbmate + codegen ------------------------------------------------------


def _env() -> dict:
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    env["PYTHONPATH"] = str(_APP) + (
        os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else ""
    )
    return env


def _run(cmd: list, cwd: Path) -> None:
    result = subprocess.run(cmd, env=_env(), cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{cmd[:2]} failed (rc={result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _dbmate_up() -> None:
    _run(["dbmate", "--migrations-dir", str(_MIGRATIONS), "up"], cwd=_BACKEND)


# NOTE: unlike pgmig-lab, we do NOT regenerate data_models on every run.
# For devops_tl, the shipped solution/ already contains the correct
# data_models (authored in the same commit as the schema change). The
# agent's task is to update both SQL + Python together; the harness
# should not silently re-derive data_models and mask mistakes.
#
# If an agent wants to regenerate after a schema tweak, the footer docs
# show them how (db/scripts/generate_sqlmodel_from_sql.py etc.).


def _session_bootstrap() -> None:
    _log("starting postgres + auth stub + redis + dbmate up")
    _start_postgres()
    _ensure_role_and_db()
    _ensure_auth_stub()
    _start_redis()
    if _MIGRATIONS.exists():
        _dbmate_up()
    _log("bootstrap complete")


_session_bootstrap()


# Known-bad pre-existing tests that fail in both base and oracle across
# multiple devops_tl tasks — noise that pollutes `flaky` counts. We skip
# them so every task's verify summary stays clean. Only add tests here
# that have been confirmed to fail identically in both states AND whose
# failure is orthogonal to the task under test.
_KNOWN_PREEXISTING_FAILURES = {
    "backend/tests/test_giftcard_issue.py::test_GI6_turns_terminal_inside_locked_section_access_failure",
}


def pytest_collection_modifyitems(config, items):
    import pytest
    skip_marker = pytest.mark.skip(reason="known pre-existing failure unrelated to devops_tl task scope")
    for item in items:
        if item.nodeid in _KNOWN_PREEXISTING_FAILURES:
            item.add_marker(skip_marker)
