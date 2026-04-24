-- migrate:up

-- Create public.users table
CREATE TABLE public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    email TEXT,
    phone TEXT,
    email_confirmed_at TIMESTAMP WITH TIME ZONE,
    phone_confirmed_at TIMESTAMP WITH TIME ZONE,
    name TEXT,
    role TEXT DEFAULT 'user' NOT NULL
);

-- Insert function
CREATE OR REPLACE FUNCTION public.handle_user_insert()
RETURNS TRIGGER AS $$
DECLARE
    user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
    INSERT INTO public.users (
        id,
        email,
        phone,
        email_confirmed_at,
        phone_confirmed_at,
        name
    )
    VALUES (
        NEW.id,
        NEW.email,
        NEW.phone,
        NEW.email_confirmed_at,
        NEW.phone_confirmed_at,
        user_name
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Update function
CREATE OR REPLACE FUNCTION public.handle_user_update()
RETURNS TRIGGER AS $$
DECLARE
    user_name TEXT := (NEW.raw_user_meta_data->>'name');
BEGIN
    UPDATE public.users
    SET
        email = NEW.email,
        phone = NEW.phone,
        email_confirmed_at = NEW.email_confirmed_at,
        phone_confirmed_at = NEW.phone_confirmed_at,
        name = user_name
    WHERE id = NEW.id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Delete function
CREATE OR REPLACE FUNCTION public.handle_user_delete()
RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM public.users WHERE id = OLD.id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Triggers
CREATE TRIGGER on_auth_user_insert
AFTER INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.handle_user_insert();

CREATE TRIGGER on_auth_user_update
AFTER UPDATE ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.handle_user_update();

CREATE TRIGGER on_auth_user_delete
AFTER DELETE ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.handle_user_delete();

-- migrate:down

-- Drop triggers and functions
DROP TRIGGER IF EXISTS on_auth_user_insert ON auth.users;
DROP TRIGGER IF EXISTS on_auth_user_update ON auth.users;
DROP TRIGGER IF EXISTS on_auth_user_delete ON auth.users;

DROP FUNCTION IF EXISTS public.handle_user_insert;
DROP FUNCTION IF EXISTS public.handle_user_update;
DROP FUNCTION IF EXISTS public.handle_user_delete;

-- Drop table
DROP TABLE IF EXISTS public.users;
