-- migrate:up
CREATE TABLE public.user_recently_viewed_photobook (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    photobook_id uuid NOT NULL REFERENCES public.photobooks(id) ON DELETE CASCADE,
    viewed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, photobook_id)
);

-- Add index for efficient querying by user_id and viewed_at
CREATE INDEX idx_user_recently_viewed_photobook_user_viewed ON public.user_recently_viewed_photobook (user_id, viewed_at DESC);

-- migrate:down
DROP INDEX IF EXISTS idx_user_recently_viewed_photobook_user_viewed;
DROP TABLE IF EXISTS public.user_recently_viewed_photobook;

