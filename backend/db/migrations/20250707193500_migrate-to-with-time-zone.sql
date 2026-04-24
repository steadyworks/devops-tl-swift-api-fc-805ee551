-- migrate:up

-- photobooks
ALTER TABLE public.photobooks
    ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE timestamp with time zone USING updated_at AT TIME ZONE 'UTC';

-- pages
ALTER TABLE public.pages
    ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC';

-- jobs
ALTER TABLE public.jobs
    ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN started_at TYPE timestamp with time zone USING started_at AT TIME ZONE 'UTC',
    ALTER COLUMN completed_at TYPE timestamp with time zone USING completed_at AT TIME ZONE 'UTC';

-- assets
ALTER TABLE public.assets
    ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC';

-- migrate:down

-- photobooks
ALTER TABLE public.photobooks
    ALTER COLUMN created_at TYPE timestamp without time zone USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE timestamp without time zone USING updated_at AT TIME ZONE 'UTC';

-- pages
ALTER TABLE public.pages
    ALTER COLUMN created_at TYPE timestamp without time zone USING created_at AT TIME ZONE 'UTC';

-- jobs
ALTER TABLE public.jobs
    ALTER COLUMN created_at TYPE timestamp without time zone USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN started_at TYPE timestamp without time zone USING started_at AT TIME ZONE 'UTC',
    ALTER COLUMN completed_at TYPE timestamp without time zone USING completed_at AT TIME ZONE 'UTC';

-- assets
ALTER TABLE public.assets
    ALTER COLUMN created_at TYPE timestamp without time zone USING created_at AT TIME ZONE 'UTC';
