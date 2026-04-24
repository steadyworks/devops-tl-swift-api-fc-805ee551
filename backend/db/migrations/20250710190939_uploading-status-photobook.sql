-- migrate:up
-- Add new photobook_status values (backward compatible)

ALTER TYPE photobook_status ADD VALUE IF NOT EXISTS 'uploading';
ALTER TYPE photobook_status ADD VALUE IF NOT EXISTS 'upload_failed';
ALTER TYPE photobook_status ADD VALUE IF NOT EXISTS 'ready_for_generation';
ALTER TYPE photobook_status ADD VALUE IF NOT EXISTS 'generating';
ALTER TYPE photobook_status ADD VALUE IF NOT EXISTS 'generation_failed';


-- migrate:down

