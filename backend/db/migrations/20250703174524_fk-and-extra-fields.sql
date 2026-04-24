-- migrate:up
-- Add enum type for user_provided_occasion
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_provided_occasion') THEN
        CREATE TYPE user_provided_occasion AS ENUM ('wedding', 'birthday', 'anniversary', 'other');
    END IF;
END$$;

-- Add columns to photobooks
ALTER TABLE public.photobooks
ADD COLUMN user_provided_occasion user_provided_occasion,
ADD COLUMN user_provided_occasion_custom_details text;

-- Add original_photobook_id to assets
ALTER TABLE public.assets
ADD COLUMN original_photobook_id uuid;

-- Add foreign key: assets.original_photobook_id → photobooks.id
ALTER TABLE public.assets
ADD CONSTRAINT assets_original_photobook_id_fkey
FOREIGN KEY (original_photobook_id) REFERENCES public.photobooks(id);

-- Add foreign key: jobs.photobook_id → photobooks.id
ALTER TABLE public.jobs
ADD CONSTRAINT jobs_photobook_id_fkey
FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id);

-- Add foreign key: pages.photobook_id → photobooks.id
ALTER TABLE public.pages
ADD CONSTRAINT pages_photobook_id_fkey
FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id);

-- Add foreign key: pages_assets_rel.page_id → pages.id
ALTER TABLE public.pages_assets_rel
ADD CONSTRAINT pages_assets_rel_page_id_fkey
FOREIGN KEY (page_id) REFERENCES public.pages(id);

-- migrate:down

-- Drop foreign keys
ALTER TABLE public.pages_assets_rel
DROP CONSTRAINT IF EXISTS pages_assets_rel_page_id_fkey;

ALTER TABLE public.pages
DROP CONSTRAINT IF EXISTS pages_photobook_id_fkey;

ALTER TABLE public.jobs
DROP CONSTRAINT IF EXISTS jobs_photobook_id_fkey;

ALTER TABLE public.assets
DROP CONSTRAINT IF EXISTS assets_original_photobook_id_fkey;

-- Drop added columns
ALTER TABLE public.assets
DROP COLUMN IF EXISTS original_photobook_id;

ALTER TABLE public.photobooks
DROP COLUMN IF EXISTS user_provided_occasion_custom_details,
DROP COLUMN IF EXISTS user_provided_occasion;

-- Drop enum type
DROP TYPE IF EXISTS user_provided_occasion;
