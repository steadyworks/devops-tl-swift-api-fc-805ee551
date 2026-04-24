-- migrate:up
ALTER TABLE pages_assets_rel DROP CONSTRAINT IF EXISTS pages_assets_rel_photo_id_fkey;
ALTER TABLE pages_assets_rel RENAME COLUMN photo_id TO asset_id;
ALTER TABLE pages_assets_rel ADD CONSTRAINT pages_assets_rel_asset_id_fkey
  FOREIGN KEY (asset_id) REFERENCES assets(id);

-- migrate:down
ALTER TABLE pages_assets_rel DROP CONSTRAINT IF EXISTS pages_assets_rel_asset_id_fkey;
ALTER TABLE pages_assets_rel RENAME COLUMN asset_id TO photo_id;
ALTER TABLE pages_assets_rel ADD CONSTRAINT pages_assets_rel_photo_id_fkey
  FOREIGN KEY (photo_id) REFERENCES assets(id);
