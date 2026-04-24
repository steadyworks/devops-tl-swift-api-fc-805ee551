-- migrate:up

ALTER TABLE public.pages
  ADD COLUMN user_message_alternative_options_outdated boolean NOT NULL DEFAULT false;

-- migrate:down

ALTER TABLE public.pages
  DROP COLUMN user_message_alternative_options_outdated;