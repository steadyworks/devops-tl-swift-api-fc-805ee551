-- migrate:up
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS assets (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    user_id UUID NOT NULL,
    asset_key_original TEXT NOT NULL,
    asset_key_display TEXT NOT NULL,
    asset_key_llm TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT DEFAULT 'queued' NOT NULL,
    input_payload JSONB,
    result_payload JSONB,
    error_message TEXT,
    user_id UUID,
    photobook_id UUID,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    completed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS photobooks (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    user_id UUID NOT NULL,
    title TEXT NOT NULL,
    caption TEXT,
    theme TEXT,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS pages (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    photobook_id UUID,
    page_number INTEGER NOT NULL,
    user_message TEXT,
    layout TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS pages_assets_rel (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    page_id UUID,
    photo_id UUID,
    order_index INTEGER,
    caption TEXT,
    PRIMARY KEY (id)
);

-- migrate:down
DROP TABLE IF EXISTS pages_assets_rel;
DROP TABLE IF EXISTS pages;
DROP TABLE IF EXISTS photobooks;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS assets;
DROP EXTENSION IF EXISTS pgcrypto;
