## Setup & Verification Requirements

### Services available in-container

- **Postgres** is running on `localhost:5432`. `DATABASE_URL` and
  `TEST_DATABASE_URL` are exported — run `echo $DATABASE_URL` for the
  concrete value. Role `photobook` and databases `photobook` +
  `photobook_test` already exist; base migrations have been applied.
  Reach it directly with `psql`, `dbmate`, or `pg_dump`.
- **Redis** is running on `localhost:6379`, no auth. `REDIS_URL` is
  exported.
- **dbmate** is on `$PATH`. `DBMATE_MIGRATIONS_DIR` points at
  `/app/backend/db/migrations`.
- External services (Stripe, Twilio, RevenueCat, Resend, Supabase Auth,
  S3) are **not** reachable. The tests selected for this task should not
  require them; if a test does, it is out of scope — do not try to stub
  production credentials.

### If your change touches the DB schema

If you add or modify a migration under `backend/db/migrations/`, you
should also regenerate the Python data models so the DAL stays
consistent. From `/app/backend`:

```bash
# 1) Apply migrations (skip dbmate's own auto-dump — we dump ourselves).
dbmate --no-dump-schema --migrations-dir /app/backend/db/migrations up

# 2) Refresh db/schema.sql (public schema only).
pg_dump "$DATABASE_URL" --schema-only --no-owner --no-privileges         --schema=public --file=/app/backend/db/schema.sql

# 3) Regenerate db/data_models/__init__.py and db/dal/schemas.py.
PYTHONPATH=/app python /app/backend/db/scripts/generate_sqlmodel_from_sql.py
mkdir -p /app/backend/db/externals
PYTHONPATH=/app python /app/backend/db/scripts/generate_crud_schemas.py
```

If your change does NOT touch the schema, you can ignore the above.

### Scope

- **Do edit:** any non-test source file under `/app/backend`.
- **Do NOT edit:** anything under `backend/tests/`, `backend/db/tests/`,
  or `backend/worker/tests/`.
- **Do NOT add new tests.** Tests are maintained separately.
