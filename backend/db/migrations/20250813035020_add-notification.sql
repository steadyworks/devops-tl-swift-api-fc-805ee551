-- migrate:up
-- 1) Enum for notification kinds
CREATE TYPE public.notification_type AS ENUM (
  'comment',
  'share',
  'mention',
  'like',
  'system',
  'custom'
);
-- 2) Main table (uuid PK to match your schema style)
CREATE TABLE public.notifications (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at        timestamptz NOT NULL DEFAULT now(),

  -- recipient & actor
  recipient_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  actor_id     uuid REFERENCES public.users(id) ON DELETE SET NULL,

  -- type
  type              public.notification_type NOT NULL,

  -- common object links (nullable)
  photobook_id      uuid REFERENCES public.photobooks(id) ON DELETE CASCADE,
  comment_id        uuid REFERENCES public.photobook_comments(id) ON DELETE CASCADE,
  share_id          uuid REFERENCES public.photobook_share(id) ON DELETE CASCADE,

  -- render helpers
  title             text,
  body              text,
  cta_url           text,

  -- flexible metadata
  payload           jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- optional dedupe key
  group_key         text,

  -- seen state
  seen_at           timestamptz
);

-- Unique-by-group (works even with NULL group_key; NULLs don’t collide)
ALTER TABLE public.notifications
  ADD CONSTRAINT notifications_group_key_unique
  UNIQUE (recipient_id, type, group_key);

-- 3) Indexes for common queries
CREATE INDEX notifications_recipient_created_idx
  ON public.notifications (recipient_id, created_at DESC);

CREATE INDEX notifications_unseen_idx
  ON public.notifications (recipient_id)
  WHERE seen_at IS NULL;

CREATE INDEX notifications_recipient_type_idx
  ON public.notifications (recipient_id, type);

CREATE INDEX notifications_payload_gin_idx
  ON public.notifications USING gin (payload);

-- migrate:down

-- Drop table (indexes & unique constraint drop with it)
DROP TABLE IF EXISTS public.notifications;

-- Drop enum type
DROP TYPE IF EXISTS public.notification_type;
