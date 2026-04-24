-- migrate:up
-- 1. Create enum type
CREATE TYPE public.asset_upload_status AS ENUM (
    'pending',
    'processing',
    'ready',
    'invalid_mime',
    'error'
);

-- 2. Add column to assets table
ALTER TABLE public.assets
ADD COLUMN upload_status public.asset_upload_status DEFAULT 'pending' NOT NULL;

-- migrate:down

-- 1. Remove column from assets
ALTER TABLE public.assets
DROP COLUMN upload_status;

-- 2. Drop enum type
DROP TYPE public.asset_upload_status;
