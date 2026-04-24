-- migrate:up
-- Enums
CREATE TYPE public.comment_status AS ENUM ('visible', 'hidden_by_author', 'deleted_by_system');
CREATE TYPE public.notification_status AS ENUM ('pending', 'sent', 'failed');

-- Main table
CREATE TABLE public.photobook_comments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    photobook_id uuid NOT NULL REFERENCES public.photobooks(id) ON DELETE CASCADE,

    -- Authenticated or guest
    user_id uuid REFERENCES public.users(id),
    guest_name text,
    guest_email text,

    body text NOT NULL,

    status public.comment_status NOT NULL DEFAULT 'visible',
    notification_status public.notification_status NOT NULL DEFAULT 'pending',

    commenter_ip text,
    user_agent text,

    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_updated_by uuid REFERENCES public.users(id),

    -- Enforce mutual exclusivity between user and guest info (app-layer preferred, but for completeness)
    CHECK (
        (user_id IS NOT NULL AND guest_name IS NULL AND guest_email IS NULL)
        OR
        (user_id IS NULL AND guest_name IS NOT NULL AND guest_email IS NOT NULL)
    )
);

-- Index to retrieve comments per photobook quickly
CREATE INDEX idx_photobook_comments_photobook_id_created_at
    ON public.photobook_comments (photobook_id, created_at DESC);
CREATE INDEX idx_photobook_comments_user_id_created_at
  ON public.photobook_comments (user_id, created_at DESC);
CREATE INDEX idx_photobook_comments_pending_notifications
  ON public.photobook_comments (notification_status)
  WHERE notification_status = 'pending';
CREATE INDEX idx_photobook_comments_status
  ON public.photobook_comments (status)
  WHERE status IN ('hidden_by_author', 'deleted_by_system');


-- migrate:down
-- Drop index first
DROP INDEX IF EXISTS idx_photobook_comments_photobook_id_created_at;
DROP INDEX IF EXISTS idx_photobook_comments_user_id_created_at;
DROP INDEX IF EXISTS idx_photobook_comments_pending_notifications;
DROP INDEX IF EXISTS idx_photobook_comments_status;

-- Drop table
DROP TABLE IF EXISTS public.photobook_comments;

-- Drop enums
DROP TYPE IF EXISTS public.notification_status;
DROP TYPE IF EXISTS public.comment_status;

