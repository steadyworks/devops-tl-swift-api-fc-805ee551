-- migrate:up

-- Replace FK on pages_assets_rel.page_id -> pages.id with ON DELETE CASCADE.
ALTER TABLE public.pages_assets_rel
  DROP CONSTRAINT IF EXISTS pages_assets_rel_page_id_fkey;

ALTER TABLE public.pages_assets_rel
  ADD CONSTRAINT pages_assets_rel_page_id_fkey
    FOREIGN KEY (page_id) REFERENCES public.pages(id)
    ON DELETE CASCADE;


-- migrate:down

-- Revert to a non-cascading FK (default NO ACTION).
ALTER TABLE public.pages_assets_rel
  DROP CONSTRAINT IF EXISTS pages_assets_rel_page_id_fkey;

ALTER TABLE public.pages_assets_rel
  ADD CONSTRAINT pages_assets_rel_page_id_fkey
    FOREIGN KEY (page_id) REFERENCES public.pages(id);
