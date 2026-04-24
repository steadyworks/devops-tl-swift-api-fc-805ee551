-- migrate:up

-- 1. Enums

-- Job event action enum: captures all lifecycle and diagnostic events
CREATE TYPE public.job_event_action AS ENUM (
  -- Core job lifecycle
  'job_queued',
  'job_dequeued',
  'attempt_started',
  'job_succeeded',
  'attempt_failed',
  'attempt_retry_scheduled',
  'attempt_retry_exhausted',
  'job_marked_dead',
  'manual_attempt_started',
  'job_enqueue_failed',

  -- Generic diagnostic logging
  'log_info',
  'log_warning',
  'log_exception'
);

COMMENT ON TYPE public.job_event_action IS 'Describes lifecycle and diagnostic events for jobs. Used in job_events.';

-- Actor type enum: for attribution of job event origin
CREATE TYPE public.actor_type AS ENUM (
  'user',
  'job_manager',
  'job_processor',
  'worker_process',
  'system'
);

COMMENT ON TYPE public.actor_type IS 'Attribution source of job_events. Indicates which actor type triggered the event.';


CREATE TYPE public.photobook_status_editor AS ENUM (
  'user',
  'upload_pipeline',
  'generation_pipeline',
  'system'
);

COMMENT ON TYPE public.photobook_status_editor IS 'Actor that triggered photobook status update.';


-- 2. Add retry tracking fields to jobs table

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
COMMENT ON COLUMN public.jobs.retry_count IS 'Number of retry attempts this job has made.';

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3;
COMMENT ON COLUMN public.jobs.max_retries IS 'Maximum retries allowed before job is marked dead.';

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ;
COMMENT ON COLUMN public.jobs.last_attempted_at IS 'Timestamp of the last job execution attempt.';

-- 3. Extend job_status enum with "dead"
ALTER TYPE public.job_status ADD VALUE IF NOT EXISTS 'dead';
COMMENT ON TYPE public.job_status IS 'Used in jobs table: now extended with value `dead` to indicate terminal failed state.';

-- 4. Add last editor source to photobooks
ALTER TABLE public.photobooks
ADD COLUMN status_last_edited_by public.photobook_status_editor DEFAULT 'user';
COMMENT ON COLUMN public.photobooks.status_last_edited_by IS 'Indicates which component last updated status.';

-- 5. Create job_events table
CREATE TABLE public.job_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    event_action public.job_event_action NOT NULL,
    message TEXT,
    host TEXT,
    retry_count INTEGER DEFAULT 0,
    context TEXT,  -- optional: e.g., 'upload', 'generation'
    extra JSONB,

    actor_type public.actor_type NOT NULL,
    actor_id TEXT
);

COMMENT ON TABLE public.job_events IS 'Immutable audit trail for job transitions, retries, errors, and debug logs.';
COMMENT ON COLUMN public.job_events.event_action IS 'Event type that occurred (e.g. retry_scheduled, log_warning).';
COMMENT ON COLUMN public.job_events.actor_type IS 'Who performed the action: system, worker, user, etc.';
COMMENT ON COLUMN public.job_events.actor_id IS 'ID of actor (e.g. user UUID, system ID, worker ID) if available.';

-- 6. Indexes for performance
CREATE INDEX idx_job_events_job_id_created_at ON public.job_events (job_id, created_at);
CREATE INDEX idx_jobs_photobook_id ON public.jobs (photobook_id);
CREATE INDEX idx_jobs_status ON public.jobs (status);
CREATE INDEX idx_jobs_job_type ON public.jobs (job_type);
CREATE INDEX idx_jobs_status_job_type ON public.jobs (status, job_type);
CREATE INDEX idx_jobs_last_attempted_at ON public.jobs (last_attempted_at);
CREATE INDEX idx_jobs_created_at ON public.jobs (created_at);
CREATE INDEX idx_jobs_status_retry_count ON public.jobs (status, retry_count);

-- 7. Explicit FK (in case it was missing)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'jobs_photobook_id_fkey'
  ) THEN
    ALTER TABLE public.jobs
    ADD CONSTRAINT jobs_photobook_id_fkey
    FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id);
  END IF;
END$$;


-- migrate:down

-- Drop indexes
DROP INDEX IF EXISTS idx_jobs_status_retry_count;
DROP INDEX IF EXISTS idx_jobs_created_at;
DROP INDEX IF EXISTS idx_jobs_last_attempted_at;
DROP INDEX IF EXISTS idx_jobs_status_job_type;
DROP INDEX IF EXISTS idx_jobs_job_type;
DROP INDEX IF EXISTS idx_jobs_status;
DROP INDEX IF EXISTS idx_jobs_photobook_id;
DROP INDEX IF EXISTS idx_job_events_job_id_created_at;

-- Drop job_events table
DROP TABLE IF EXISTS public.job_events;

-- Drop added columns from jobs
ALTER TABLE public.jobs DROP COLUMN IF EXISTS retry_count;
ALTER TABLE public.jobs DROP COLUMN IF EXISTS max_retries;
ALTER TABLE public.jobs DROP COLUMN IF EXISTS last_attempted_at;

-- Drop added column from photobooks
ALTER TABLE public.photobooks DROP COLUMN IF EXISTS status_last_edited_by;

-- Drop enums
DROP TYPE IF EXISTS public.job_event_action;
DROP TYPE IF EXISTS public.actor_type;
DROP TYPE IF EXISTS public.photobook_status_editor;