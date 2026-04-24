-- migrate:up
ALTER TABLE public.assets
ADD COLUMN blur_data_url TEXT;

-- migrate:down
ALTER TABLE public.assets
DROP COLUMN blur_data_url;