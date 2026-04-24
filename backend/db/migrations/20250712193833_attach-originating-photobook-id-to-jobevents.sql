-- migrate:up

ALTER TABLE public.job_events
ADD COLUMN photobook_id uuid;

ALTER TABLE public.job_events
ADD CONSTRAINT job_events_photobook_id_fkey
FOREIGN KEY (photobook_id)
REFERENCES public.photobooks(id)
ON DELETE SET NULL;

CREATE INDEX idx_job_events_photobook_id ON public.job_events (photobook_id);

-- migrate:down

ALTER TABLE public.job_events
DROP CONSTRAINT job_events_photobook_id_fkey;

ALTER TABLE public.job_events
DROP COLUMN photobook_id;

DROP INDEX IF EXISTS idx_job_events_photobook_id;
