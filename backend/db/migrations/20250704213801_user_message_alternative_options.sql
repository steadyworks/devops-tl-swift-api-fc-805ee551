-- migrate:up

ALTER TABLE public.pages
ADD COLUMN user_message_alternative_options jsonb;

-- migrate:down

ALTER TABLE public.pages
DROP COLUMN user_message_alternative_options;
