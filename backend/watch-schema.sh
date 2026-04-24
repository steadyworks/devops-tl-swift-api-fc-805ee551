#!/bin/bash
echo "[👀] Watching db/schema.sql for writes..."
fswatch -0 db/schema.sql | xargs -0 -n1 -I{} bash -c '
  echo "[🔍] schema.sql modified at $(date)";
  lsof db/schema.sql;
  echo "---"
'