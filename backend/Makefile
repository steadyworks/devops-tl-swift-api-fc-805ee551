.SILENT:  # Suppress command echoing globally for safety

SUPABASE_DEV_URI := $(shell grep SUPABASE_POSTGRES_URI_DBADMIN .env.dev | cut -d '=' -f2-)
SUPABASE_PROD_URI := $(shell [ -f .env.prod ] && grep SUPABASE_POSTGRES_URI_DBADMIN .env.prod | cut -d '=' -f2- || echo "")
# SUPABASE_PROD_URI := $(shell grep SUPABASE_POSTGRES_URI_DBADMIN .env.prod | cut -d '=' -f2-)
MIGRATIONS_DIR := db/migrations

# Create a new timestamped migration file
new-migration:
ifndef name
	$(error Usage: make new-migration name=create_table_example)
endif
	@dbmate --migrations-dir $(MIGRATIONS_DIR) new $(name)

# Apply all unapplied migrations
migrate-dev:
	@$(info Running migrate-dev...)
	@DATABASE_URL=$(SUPABASE_DEV_URI) dbmate --no-dump-schema --migrations-dir $(MIGRATIONS_DIR) up
	@$(MAKE) dump-schema-dev generate-schema-artifacts

migrate-prod:
	@$(info Running migrate-prod...)
	@DATABASE_URL=$(SUPABASE_PROD_URI) dbmate --no-dump-schema --migrations-dir $(MIGRATIONS_DIR) up
	@$(MAKE) dump-schema-prod generate-schema-artifacts

# Roll back the last migration
rollback-dev:
	@$(info Rolling back last dev migration...)
	@DATABASE_URL=$(SUPABASE_DEV_URI) dbmate --no-dump-schema --migrations-dir $(MIGRATIONS_DIR) down
	@$(MAKE) dump-schema-dev generate-schema-artifacts

rollback-prod:
	@$(info Rolling back last prod migration...)
	@DATABASE_URL=$(SUPABASE_PROD_URI) dbmate --no-dump-schema --migrations-dir $(MIGRATIONS_DIR) down
	@$(MAKE) dump-schema-prod generate-schema-artifacts

# Show migration status
status-dev:
	@DATABASE_URL=$(SUPABASE_DEV_URI) dbmate --migrations-dir $(MIGRATIONS_DIR) status

status-prod:
	@DATABASE_URL=$(SUPABASE_PROD_URI) dbmate --migrations-dir $(MIGRATIONS_DIR) status

# Dump schema from dev
dump-schema-dev:
	@PGPASSWORD=$$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*:([^@]+)@.*/\1/') \
	pg_dump --schema-only --no-owner --no-privileges --schema=public \
	--username=$$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*\/\/([^:]+):.*/\1/') \
	--host=$$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*@([^:\/]+).*/\1/') \
	--port=5432 \
	--dbname=$$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*\/([^?]+).*/\1/') \
	--file=db/schema.sql

# Dump schema from prod
dump-schema-prod:
	@PGPASSWORD=$$(echo $(SUPABASE_PROD_URI) | sed -E 's/.*:([^@]+)@.*/\1/') \
	pg_dump --schema-only --no-owner --no-privileges --schema=public \
	--username=$$(echo $(SUPABASE_PROD_URI) | sed -E 's/.*\/\/([^:]+):.*/\1/') \
	--host=$$(echo $(SUPABASE_PROD_URI) | sed -E 's/.*@([^:\/]+).*/\1/') \
	--port=5432 \
	--dbname=$$(echo $(SUPABASE_PROD_URI) | sed -E 's/.*\/([^?]+).*/\1/') \
	--file=db/schema.prod.sql

# Reset dev DB (wipe schema)
reset-dev:
	@echo "[WARN] Resetting dev DB: dropping and recreating public schema..."
	@PGPASSWORD=$$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*:([^@]+)@.*/\1/') \
	psql -U $$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*\/\/([^:]+):.*/\1/') \
	-h $$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*@([^:\/]+).*/\1/') \
	-d $$(echo $(SUPABASE_DEV_URI) | sed -E 's/.*\/([^?]+).*/\1/') \
	-c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Prevent accidental prod data drop
reset-prod:
	@echo "[STOP] DO NOT RESET PROD. This will drop all production data."

# Regenerate code artifacts from schema.sql
generate-schema-artifacts:
	@PYTHONPATH=.. python db/scripts/generate_sqlmodel_from_sql.py
	@PYTHONPATH=.. python db/scripts/generate_crud_schemas.py
