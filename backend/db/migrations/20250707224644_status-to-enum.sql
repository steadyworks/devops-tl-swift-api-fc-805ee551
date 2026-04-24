-- migrate:up
-- 1. Create ENUM types
CREATE TYPE photobook_status AS ENUM (
    'draft',
    'pending',
    'deleted',
    'permanently_deleted',
    'published'
);

CREATE TYPE job_status AS ENUM (
    'queued',
    'dequeued',
    'processing',
    'done',
    'error'
);

-- 2. Drop default before altering column type
ALTER TABLE public.photobooks
    ALTER COLUMN status DROP DEFAULT;

ALTER TABLE public.jobs
    ALTER COLUMN status DROP DEFAULT;

-- 3. Alter column type
ALTER TABLE public.photobooks
    ALTER COLUMN status TYPE photobook_status
    USING status::photobook_status;

ALTER TABLE public.jobs
    ALTER COLUMN status TYPE job_status
    USING status::job_status;

-- 4. Restore default
ALTER TABLE public.photobooks
    ALTER COLUMN status SET DEFAULT 'draft';

ALTER TABLE public.jobs
    ALTER COLUMN status SET DEFAULT 'queued';





-- migrate:down
ALTER TABLE public.photobooks
    ALTER COLUMN status DROP DEFAULT;

ALTER TABLE public.jobs
    ALTER COLUMN status DROP DEFAULT;

-- 2. Revert to text
ALTER TABLE public.photobooks
    ALTER COLUMN status TYPE text
    USING status::text;

ALTER TABLE public.jobs
    ALTER COLUMN status TYPE text
    USING status::text;

-- 3. Restore original text default
ALTER TABLE public.photobooks
    ALTER COLUMN status SET DEFAULT 'draft';

ALTER TABLE public.jobs
    ALTER COLUMN status SET DEFAULT 'queued';

-- 4. Drop ENUMs
DROP TYPE IF EXISTS photobook_status;
DROP TYPE IF EXISTS job_status;
