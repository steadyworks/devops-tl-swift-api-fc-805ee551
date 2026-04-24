-- migrate:up

CREATE TYPE public.share_role AS ENUM ('viewer', 'editor', 'owner');

-- Create the photobook_share table
CREATE TABLE photobook_share (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  photobook_id UUID NOT NULL,
  email TEXT,
  invited_user_id UUID,
  role public.share_role NOT NULL DEFAULT 'viewer',
  email_notification_status public.notification_status DEFAULT 'pending',
  custom_message TEXT,


  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Foreign keys
  CONSTRAINT fk_photobook FOREIGN KEY (photobook_id) REFERENCES photobooks (id) ON DELETE CASCADE,
  CONSTRAINT fk_invited_user FOREIGN KEY (invited_user_id) REFERENCES users (id) ON DELETE SET NULL,

  -- Ensure either raw email or invited_user_id is present (not both null)
  CONSTRAINT email_or_user_check CHECK (
    (email IS NOT NULL AND invited_user_id IS NULL)
    OR (email IS NULL AND invited_user_id IS NOT NULL)
  ),

  -- Prevent duplicate share entries
  CONSTRAINT unique_share_per_target UNIQUE (photobook_id, email, invited_user_id)
);

-- Optional: index for quick lookup of shares for a given user
CREATE INDEX idx_photobook_share_invited_user_id ON photobook_share (invited_user_id);

-- Optional: index for lookup by email
CREATE INDEX idx_photobook_share_email ON photobook_share (email);

-- migrate:down

DROP INDEX IF EXISTS idx_photobook_share_email;
DROP INDEX IF EXISTS idx_photobook_share_invited_user_id;
DROP TABLE IF EXISTS photobook_share;