-- migrate:up
ALTER TABLE public.photobooks
ADD COLUMN deleted_at timestamp with time zone;


-- migrate:down
ALTER TABLE public.photobooks
DROP COLUMN deleted_at;

