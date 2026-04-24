-- migrate:up

-- Keep the original type name in use by doing a rename + recreate
ALTER TYPE public.photobook_status RENAME TO photobook_status_old;

-- New reduced enum (without the pipeline states)
CREATE TYPE public.photobook_status AS ENUM (
  'draft',
  'pending',
  'deleted',
  'permanently_deleted',
  'published'
);

-- Drop default to avoid conflicts while changing type
ALTER TABLE public.photobooks
  ALTER COLUMN status DROP DEFAULT;

-- Coerce any removed states to an allowed value before the cast
UPDATE public.photobooks
SET status = 'pending'
WHERE status::text IN (
  'uploading',
  'upload_failed',
  'ready_for_generation',
  'generating',
  'generation_failed'
);

-- Change the column to the new enum
ALTER TABLE public.photobooks
  ALTER COLUMN status TYPE public.photobook_status
  USING status::text::public.photobook_status;

-- Restore default if desired
ALTER TABLE public.photobooks
  ALTER COLUMN status SET DEFAULT 'draft';

-- Old type no longer referenced; safe to drop
DROP TYPE public.photobook_status_old;

-- migrate:down

-- Recreate the superset enum (with the five pipeline states) under a temp name
CREATE TYPE public.photobook_status_old AS ENUM (
  'draft',
  'pending',
  'deleted',
  'permanently_deleted',
  'published',
  'uploading',
  'upload_failed',
  'ready_for_generation',
  'generating',
  'generation_failed'
);

-- Drop default to allow type change
ALTER TABLE public.photobooks
  ALTER COLUMN status DROP DEFAULT;

-- Cast back to the superset enum
ALTER TABLE public.photobooks
  ALTER COLUMN status TYPE public.photobook_status_old
  USING status::text::public.photobook_status_old;

-- Replace the reduced enum with the superset
DROP TYPE public.photobook_status;
ALTER TYPE public.photobook_status_old RENAME TO public.photobook_status;

-- Restore default
ALTER TABLE public.photobooks
  ALTER COLUMN status SET DEFAULT 'draft';
