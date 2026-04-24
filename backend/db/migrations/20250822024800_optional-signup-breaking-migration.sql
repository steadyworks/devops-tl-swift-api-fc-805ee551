-- migrate:up

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

-- If you use gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

---------------------------
-- 1) Identity plumbing  --
---------------------------

-- 1a) Enum for identity kinds
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'identity_kind') THEN
    CREATE TYPE public.identity_kind AS ENUM ('guest','user');
  END IF;
END$$;

-- 1b) Canonical owners
CREATE TABLE IF NOT EXISTS public.owners (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 1c) Owner ↔ identity mapping (surrogate PK to keep ORMs happy)
CREATE TABLE IF NOT EXISTS public.owner_identities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES public.owners(id) ON DELETE CASCADE,
  kind public.identity_kind NOT NULL,
  identity uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  -- business invariants:
  CONSTRAINT owner_identities_kind_identity_key UNIQUE (kind, identity),
  CONSTRAINT owner_kind_unique UNIQUE (owner_id, kind)
);

CREATE INDEX IF NOT EXISTS owner_identities_owner_idx
  ON public.owner_identities(owner_id);
CREATE INDEX IF NOT EXISTS owner_identities_identity_lookup
  ON public.owner_identities(kind, identity);

--------------------------------------------------------
-- 2) Backfill owner records from existing user_ids   --
--    (only users that actually own assets/photobooks) --
--------------------------------------------------------

-- TEMP tables must NOT be schema-qualified
DROP TABLE IF EXISTS _tmp_user_to_owner_map;
CREATE TEMP TABLE _tmp_user_to_owner_map (
  user_id uuid PRIMARY KEY,
  owner_id uuid NOT NULL
) ON COMMIT DROP;

INSERT INTO _tmp_user_to_owner_map (user_id, owner_id)
SELECT u.user_id, gen_random_uuid()
FROM (
  SELECT DISTINCT user_id FROM public.assets
  UNION
  SELECT DISTINCT user_id FROM public.photobooks
) AS u;

-- Create owners for those user_ids
INSERT INTO public.owners (id)
SELECT DISTINCT owner_id
FROM _tmp_user_to_owner_map
ON CONFLICT (id) DO NOTHING;

-- Attach identity(kind='user', identity=user_id) → owner_id
INSERT INTO public.owner_identities (owner_id, kind, identity)
SELECT m.owner_id, 'user'::public.identity_kind, m.user_id
FROM _tmp_user_to_owner_map m
ON CONFLICT (kind, identity) DO NOTHING;

-----------------------------------------------
-- 3) Move assets & photobooks to owner_id    --
-----------------------------------------------

ALTER TABLE public.assets     ADD COLUMN IF NOT EXISTS owner_id uuid;
ALTER TABLE public.photobooks ADD COLUMN IF NOT EXISTS owner_id uuid;

UPDATE public.assets a
SET owner_id = m.owner_id
FROM _tmp_user_to_owner_map m
WHERE a.user_id = m.user_id;

UPDATE public.photobooks p
SET owner_id = m.owner_id
FROM _tmp_user_to_owner_map m
WHERE p.user_id = m.user_id;

ALTER TABLE public.assets
  ALTER COLUMN owner_id SET NOT NULL,
  ADD CONSTRAINT assets_owner_fk
    FOREIGN KEY (owner_id) REFERENCES public.owners(id);

ALTER TABLE public.photobooks
  ALTER COLUMN owner_id SET NOT NULL,
  ADD CONSTRAINT photobooks_owner_fk
    FOREIGN KEY (owner_id) REFERENCES public.owners(id);

CREATE INDEX IF NOT EXISTS idx_assets_owner_id     ON public.assets(owner_id);
CREATE INDEX IF NOT EXISTS idx_photobooks_owner_id ON public.photobooks(owner_id);

-- BREAKING: remove legacy columns
ALTER TABLE public.assets     DROP COLUMN IF EXISTS user_id;
ALTER TABLE public.photobooks DROP COLUMN IF EXISTS user_id;

-- migrate:down

-- BREAKING MIGRATION - permanent