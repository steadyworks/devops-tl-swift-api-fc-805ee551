-- migrate:up
-- 1. Create font_style enum
CREATE TYPE public.font_style AS ENUM ('unspecified');

-- 2. Create table
CREATE TABLE public.photobook_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    photobook_id uuid NOT NULL,
    main_style text,
    font public.font_style NOT NULL DEFAULT 'unspecified',

    is_comment_enabled boolean NOT NULL DEFAULT false,
    is_allow_download_all_images_enabled boolean NOT NULL DEFAULT false,
    is_tipping_enabled boolean NOT NULL DEFAULT false,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_photobook FOREIGN KEY (photobook_id)
        REFERENCES public.photobooks(id)
        ON DELETE CASCADE,

    CONSTRAINT uq_photobook_settings_photobook_id UNIQUE (photobook_id)
);

-- 3. Explicit index (redundant due to UNIQUE, but included for clarity/performance tuning)
CREATE UNIQUE INDEX idx_photobook_settings_photobook_id
    ON public.photobook_settings (photobook_id);


-- migrate:down
-- Drop index explicitly
DROP INDEX IF EXISTS idx_photobook_settings_photobook_id;

-- Drop table
DROP TABLE IF EXISTS public.photobook_settings;

-- Drop enum
DROP TYPE IF EXISTS public.font_style;

