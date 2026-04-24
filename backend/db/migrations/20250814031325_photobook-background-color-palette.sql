-- migrate:up

ALTER TABLE public.photobooks
ADD COLUMN background_color_palette TEXT;

-- migrate:down

ALTER TABLE public.photobooks
DROP COLUMN IF EXISTS background_color_palette;