-- migrate:up

ALTER TABLE public.assets
ADD COLUMN original_filename text;



-- migrate:down

ALTER TABLE public.assets
DROP COLUMN original_filename;

