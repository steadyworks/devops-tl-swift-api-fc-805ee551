-- migrate:up
ALTER TABLE public.assets
ADD COLUMN exif jsonb;

-- migrate:down
ALTER TABLE public.assets
DROP COLUMN exif;
