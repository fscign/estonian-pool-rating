#!/bin/sh
# Downloads the raw data from fscign/pool-data (release "data", replaced by every collection run).
# If a release file can't be downloaded, the starting copy in the pool-data repo is used.
mkdir -p data status
FILES="ts_raw.json.gz baltic_extra_ts_raw.json.gz epbf_data.json.gz wnt_data.json.gz pbs_data.json.gz"
for c in ee lv lt baltic_extra fi se dk no; do FILES="$FILES ${c}_cuescore_raw.json.gz"; done
for f in $FILES; do
  if curl -fsSL --retry 3 -o "data/$f.new" "https://github.com/fscign/pool-data/releases/download/data/$f"; then mv "data/$f.new" "data/$f"
  elif curl -fsSL --retry 3 -o "data/$f.new" "https://raw.githubusercontent.com/fscign/pool-data/main/data/$f"; then mv "data/$f.new" "data/$f"; echo "$f: release file missing, used the starting copy"
  else rm -f "data/$f.new"; echo "$f: NOT downloaded"; fi
done
# Shared score and event rules (one copy for every rating)
curl -fsSL --retry 3 -o data/score_rules.py.new "https://raw.githubusercontent.com/fscign/pool-data/main/rules/score_rules.py" && mv data/score_rules.py.new data/score_rules.py || echo "score_rules.py: NOT downloaded"
gh release download data -R fscign/pool-data -p 'status_*' -D status --clobber 2>/dev/null || echo "status files not downloaded"
