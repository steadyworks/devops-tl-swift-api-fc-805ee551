# DB schema change

1. Any DB schema change needs to be backwards compatible
2. Use `cd backend && make new-migration name="migration-name"` to initiate a migration
3. It will create a new .sql file under migrations/
4. Fill out the -- migrate:up and -- migrate:down SQL commands
5. `cd backend && make migrate-dev` to apply migration to dev, and codegen
6. Once verify that dev fully works (new schema + new code / business logic), git commit

# Productionize

1. git push main → triggers code deploy via GitHub Actions
2. GitHub Action lints + deploys app code to VPS (no DB changes yet)
3. **Once you're sure the code is live and stable:**
4. Run: make migrate-prod
