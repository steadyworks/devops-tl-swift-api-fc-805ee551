-- migrate:up

ALTER TABLE photobooks
ADD COLUMN user_provided_context TEXT;

-- migrate:down

ALTER TABLE photobooks
DROP COLUMN user_provided_context;
