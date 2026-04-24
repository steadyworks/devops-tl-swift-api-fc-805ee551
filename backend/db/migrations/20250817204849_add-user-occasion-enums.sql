-- migrate:up
ALTER TYPE public.user_provided_occasion
    ADD VALUE IF NOT EXISTS 'gift';
ALTER TYPE public.user_provided_occasion
    ADD VALUE IF NOT EXISTS 'memory';
ALTER TYPE public.user_provided_occasion
    ADD VALUE IF NOT EXISTS 'trip';

-- migrate:down
-- ⚠️ PostgreSQL does not support removing values from an ENUM directly.
-- To rollback, we need to recreate the type without the added values.

DO $$
BEGIN
    -- Create a new enum without the added values
    CREATE TYPE public.user_provided_occasion_old AS ENUM (
        'wedding',
        'birthday',
        'anniversary',
        'other'
    );

    -- Change columns using the enum back to the old one
    ALTER TABLE public.photobooks
        ALTER COLUMN user_provided_occasion
        TYPE public.user_provided_occasion_old
        USING user_provided_occasion::text::public.user_provided_occasion_old;

    -- Drop the updated enum and rename the old one back
    DROP TYPE public.user_provided_occasion;
    ALTER TYPE public.user_provided_occasion_old RENAME TO user_provided_occasion;
END $$;
