-- migrate:up
CREATE TABLE public.photobooks_assets_rel (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    photobook_id uuid NOT NULL,
    asset_id uuid NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT photobooks_assets_rel_photobook_id_fkey
        FOREIGN KEY (photobook_id)
        REFERENCES public.photobooks(id)
        ON DELETE CASCADE,
    CONSTRAINT photobooks_assets_rel_asset_id_fkey
        FOREIGN KEY (asset_id)
        REFERENCES public.assets(id)
        ON DELETE CASCADE,
    CONSTRAINT photobooks_assets_rel_unique_pair UNIQUE (photobook_id, asset_id)
);

CREATE INDEX idx_photobooks_assets_rel_photobook_id ON public.photobooks_assets_rel (photobook_id);
CREATE INDEX idx_photobooks_assets_rel_asset_id ON public.photobooks_assets_rel (asset_id);

-- migrate:down
DROP TABLE public.photobooks_assets_rel;
