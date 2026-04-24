-- migrate:up

ALTER TABLE public.users
ADD COLUMN bmc_link TEXT NULL;

-- migrate:down

ALTER TABLE public.users
DROP COLUMN IF EXISTS bmc_link;