-- migrate:up
ALTER TABLE public.jobs
    ALTER COLUMN user_id DROP NOT NULL,
    ADD COLUMN owner_id uuid;

ALTER TABLE public.jobs
    ADD CONSTRAINT jobs_owner_fk FOREIGN KEY (owner_id)
        REFERENCES public.owners (id);

CREATE INDEX idx_jobs_owner_id ON public.jobs (owner_id);

-- migrate:down
ALTER TABLE public.jobs
    DROP CONSTRAINT jobs_owner_fk,
    DROP COLUMN owner_id;

ALTER TABLE public.jobs
    ALTER COLUMN user_id SET NOT NULL;
