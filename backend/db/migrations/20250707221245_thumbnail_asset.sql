-- migrate:up

ALTER TABLE public.photobooks
ADD COLUMN thumbnail_asset_id uuid;

ALTER TABLE public.photobooks
ADD CONSTRAINT photobooks_thumbnail_asset_id_fkey
FOREIGN KEY (thumbnail_asset_id)
REFERENCES public.assets(id)
ON DELETE SET NULL;

-- Optional: index for performance if you query/filter by thumbnail_asset_id
CREATE INDEX idx_photobooks_thumbnail_asset_id
ON public.photobooks(thumbnail_asset_id);



-- migrate:down
-- Drop index first to avoid dependency errors
DROP INDEX IF EXISTS idx_photobooks_thumbnail_asset_id;

ALTER TABLE public.photobooks
DROP CONSTRAINT IF EXISTS photobooks_thumbnail_asset_id_fkey;

ALTER TABLE public.photobooks
DROP COLUMN IF EXISTS thumbnail_asset_id;
