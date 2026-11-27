#!/bin/sh
# Daily update of the Estonian Pool Rating: (get data) -> league list -> build -> rate -> export -> admin data -> report.txt
set -e
cd "$(dirname "$0")"
rm -f update_log.txt
cp site/data.json previous_data.json 2>/dev/null || echo '{"players":[],"tournaments":[],"matches":[]}' > previous_data.json
if [ "$1" = "--get-data" ]; then sh get_data.sh; fi
python3 -I fetch_leagues.py | tee -a update_log.txt || echo "league list step failed, kept the old list" | tee -a update_log.txt
python3 -I build_db.py > build_log.txt 2>&1
python3 -I fargo/daily_lookup.py | tee -a update_log.txt || echo "FargoRate lookup failed, kept the old results" | tee -a update_log.txt
python3 -I rate.py > rate_log.txt
python3 -I export.py
python3 -I export_admin.py
python3 -I report.py previous_data.json
