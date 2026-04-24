-- migrate:up
ALTER TABLE public.photobooks
    ADD COLUMN user_gift_recipient TEXT,
    ADD COLUMN suggested_overall_gift_message TEXT,
    ADD COLUMN suggested_overall_gift_message_tone TEXT,
    ADD COLUMN suggested_overall_gift_message_alternative_options JSONB;

-- migrate:down
ALTER TABLE public.photobooks
    DROP COLUMN user_gift_recipient,
    DROP COLUMN suggested_overall_gift_message,
    DROP COLUMN suggested_overall_gift_message_tone,
    DROP COLUMN suggested_overall_gift_message_alternative_options;
