-- migrate:up
ALTER TABLE public.assets
ADD COLUMN asset_key_thumbnail text;


-- migrate:down
ALTER TABLE public.assets
DROP COLUMN asset_key_thumbnail;
