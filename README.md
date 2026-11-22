# Estonian Pool Rating

Fargo-style rating for Estonian pool players (planned address ee.poolrating.eu). Built like the Latvian rating
(fscign/latvian-pool-rating); the raw data comes from fscign/pool-data (release "data").

- `get_data.sh`: downloads Tournament Service, CueScore Estonia/Latvia/Lithuania/Finland/Sweden/Denmark/Norway, EPBF, Matchroom, PBS.
- `build_db.py`: Latvian rules (8/9/10-ball races to 3+, 14.1 to 50+, no handicap, no doubles/team events, duplicates across sites counted once), player merges; every match is rated, only Estonians are shown.
- `rate.py`: ratings with a 2-year half-life, scale placed by 15 Estonian reference players (FargoRate, robustness 1,000+).
- `export.py`: site/data.json (Estonians, their opponents, matches with an Estonian).
- `overrides.json`: manual decisions (starts as a copy of the Latvian file; 'estonian' = CueScore profiles with a wrong flag that are Estonian).

Run: `./get_data.sh && python3 build_db.py && python3 rate.py && python3 export.py`
