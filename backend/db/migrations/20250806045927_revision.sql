-- migrate:up

ALTER TABLE public.pages
  ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;

-- migrate:down

ALTER TABLE public.pages
  DROP COLUMN IF EXISTS revision;


