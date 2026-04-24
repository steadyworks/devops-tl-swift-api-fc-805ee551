-- migrate:up
CREATE INDEX IF NOT EXISTS idx_pages_assets_rel_page_id ON public.pages_assets_rel (page_id);
CREATE INDEX IF NOT EXISTS idx_pages_assets_rel_asset_id ON public.pages_assets_rel (asset_id);
CREATE INDEX IF NOT EXISTS idx_pages_photobook_id ON public.pages (photobook_id);

-- migrate:down
DROP INDEX IF EXISTS idx_pages_assets_rel_page_id;
DROP INDEX IF EXISTS idx_pages_assets_rel_asset_id;
DROP INDEX IF EXISTS idx_pages_photobook_id;
