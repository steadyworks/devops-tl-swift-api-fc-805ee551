-- migrate:up
ALTER TABLE public.assets
ALTER COLUMN asset_key_original DROP NOT NULL;

-- migrate:down
ALTER TABLE public.assets
ALTER COLUMN asset_key_original SET NOT NULL;
