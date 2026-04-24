-- migrate:up

ALTER TABLE public.assets
  RENAME COLUMN metadata TO metadata_json;

ALTER TABLE public.assets
  ALTER COLUMN asset_key_display DROP NOT NULL,
  ALTER COLUMN asset_key_llm DROP NOT NULL;

-- migrate:down

ALTER TABLE public.assets
  RENAME COLUMN metadata_json TO metadata;

-- You'll need to ensure no nulls exist before making these NOT NULL again
UPDATE public.assets
  SET asset_key_display = '<FIXME>' 
  WHERE asset_key_display IS NULL;

UPDATE public.assets
  SET asset_key_llm = '<FIXME>' 
  WHERE asset_key_llm IS NULL;

ALTER TABLE public.assets
  ALTER COLUMN asset_key_display SET NOT NULL,
  ALTER COLUMN asset_key_llm SET NOT NULL;
