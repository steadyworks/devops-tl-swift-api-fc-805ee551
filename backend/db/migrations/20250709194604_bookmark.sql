-- migrate:up
CREATE TABLE IF NOT EXISTS public.photobook_bookmarks (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid NOT NULL,
    photobook_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    source text, -- e.g. 'search', 'home_feed', 'direct_link'

    CONSTRAINT fk_bookmark_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_bookmark_photobook FOREIGN KEY (photobook_id) REFERENCES public.photobooks(id) ON DELETE CASCADE,
    CONSTRAINT unique_user_photobook UNIQUE (user_id, photobook_id)
);

CREATE INDEX IF NOT EXISTS idx_photobook_bookmarks_user_id
ON public.photobook_bookmarks (user_id);

-- migrate:down
DROP INDEX IF EXISTS idx_photobook_bookmarks_user_id;
DROP TABLE IF EXISTS public.photobook_bookmarks;
