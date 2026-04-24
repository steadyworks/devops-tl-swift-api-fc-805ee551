-- migrate:up
ALTER TABLE public.job_events
    DROP COLUMN context,
    ADD COLUMN job_type TEXT;


ALTER TYPE public.job_status
ADD VALUE IF NOT EXISTS 'enqueue_failed';


-- migrate:down
ALTER TABLE public.job_events
    DROP COLUMN job_type,
    ADD COLUMN context TEXT;
