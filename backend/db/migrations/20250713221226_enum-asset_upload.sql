-- migrate:up
-- 0. Drop the default so the cast can proceed
ALTER TABLE public.assets
  ALTER COLUMN upload_status DROP DEFAULT;

-- 1. Park the old enum under a new name
ALTER TYPE public.asset_upload_status
  RENAME TO asset_upload_status_old;

-- 2. Create the replacement enum with the desired values
CREATE TYPE public.asset_upload_status AS ENUM (
    'pending',
    'processing',
    'ready',
    'invalid_mime',
    'processing_failed',   -- renamed value
    'upload_failed',       -- brand-new value
    'upload_succeeded'       -- brand-new value
);

-- 3. Re-cast the column, mapping 'error' → 'processing_error' on the fly
ALTER TABLE public.assets
  ALTER COLUMN upload_status TYPE public.asset_upload_status
  USING (
    CASE upload_status::text
         WHEN 'error' THEN 'processing_failed'
         ELSE upload_status::text
    END
  )::public.asset_upload_status;

-- 4. Remove the obsolete enum
DROP TYPE public.asset_upload_status_old;

-- 5. Restore the default
ALTER TABLE public.assets
  ALTER COLUMN upload_status SET DEFAULT 'pending';





-- migrate:down
-- 0. Drop default first
ALTER TABLE public.assets
  ALTER COLUMN upload_status DROP DEFAULT;

-- 1. Park the current enum
ALTER TYPE public.asset_upload_status
  RENAME TO asset_upload_status_new;

-- 2. Re-create the original enum
CREATE TYPE public.asset_upload_status AS ENUM (
    'pending',
    'processing',
    'ready',
    'invalid_mime',
    'error'
);

-- 3. Cast the column back, mapping new values to something legal
ALTER TABLE public.assets
  ALTER COLUMN upload_status TYPE public.asset_upload_status
  USING (
    CASE upload_status::text
         WHEN 'processing_error' THEN 'error'
         WHEN 'upload_failed'     THEN 'error'
         ELSE upload_status::text
    END
  )::public.asset_upload_status;

-- 4. Drop the temporary enum
DROP TYPE public.asset_upload_status_new;

-- 5. Restore the default
ALTER TABLE public.assets
  ALTER COLUMN upload_status SET DEFAULT 'pending';
