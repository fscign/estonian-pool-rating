"""Data for the admin panel: site/admin/data.json (behind Cloudflare Access, only Aleksandrs).
Runs after build_db.py and export.py. Reads ee_pool.sqlite, data/ts_raw.json.gz, overrides.json, admin_dups.json and cs_times.json (CueScore match times, cached).
Only Estonians, their opponents and tournaments with an Estonian (or held in Estonia) go in, so the file stays small."""
import sqlite3, json, collections, datetime, os, time, statistics, gzip
import requests

db = sqlite3.connect('ee_pool.sqlite')
raw = json.load(gzip.open('data/ts_raw.json.gz', 'rt', encoding='utf-8')) if os.path.exists('data/ts_raw.json.gz') else {'matches': []}
OV = json.load(open('overrides.json', encoding='utf-8'))
DUPS = json.load(open('admin_dups.json', encoding='utf-8'))
DUP_IDS = {p[k] for p in DUPS for k in ('a', 'b')}
LV = {}
CST = json.load(open('cs_times.json')) if os.path.exists('cs_times.json') else {}

# ---------- players ----------
first_last = {pid: (a, b) for pid, a, b in db.execute(
    'SELECT p, MIN(d), MAX(d) FROM (SELECT player_a p, date d FROM matches UNION ALL SELECT player_b, date FROM matches) GROUP BY p')}
prof = collections.defaultdict(lambda: dict(ts=[], cs=[]))
for src, sid, pid, name in db.execute('SELECT source, source_id, player_id, name_on_source FROM player_profiles'):
    if src == 'cuescore': prof[pid]['cs'].append([sid, name])
    else:
        lv = LV.get(sid)
        prof[pid]['ts'].append([sid, name, f'{lv[1]} {lv[0]}' if lv else ''])
EST = {pid for (pid,) in db.execute('SELECT id FROM players WHERE shown=1')}
NEAR = set(EST)
for a, b in db.execute('SELECT player_a, player_b FROM matches'):
    if a in EST or b in EST: NEAR.update((a, b))
players = []
for r in db.execute('''SELECT p.id, p.first_name, p.last_name, p.country, p.city, p.sex, p.shown, r.rating, r.racks, r.matches, p.club, p.league
                       FROM players p LEFT JOIN ratings r ON r.player_id=p.id'''):
    pid = r[0]
    if pid not in NEAR: continue
    fl = first_last.get(pid, ('', ''))
    players.append(dict(id=pid, first=r[1], last=r[2], country=r[3], city=r[4], sex=r[5], shown=r[6],
                        rating=round(r[7]) if r[7] else None, racks=r[8], matches=r[9], since=fl[0], last_match=fl[1],
                        ts=prof[pid]['ts'], cs=prof[pid]['cs'], club=r[10], league=r[11]))

# ---------- tournaments ----------
LAT = EST   # 'lat' = number of Estonian players (the panel shows it as EE)
cnt = collections.Counter(); pl = collections.defaultdict(set)
for t, a, b in db.execute('SELECT tournament_id, player_a, player_b FROM matches'):
    cnt[t] += 1; pl[t].update((a, b))
tours = []
for r in db.execute('SELECT id, source, name, date, city, club, game, excluded_reason, url FROM tournaments ORDER BY date DESC, id DESC'):
    t = r[0]
    if not (pl[t] & EST) and not ((r[4] or '') + ' ').lower().startswith(('tallinn', 'tartu', 'pärnu', 'parnu', 'narva')) and t not in DUP_IDS: continue
    reason = r[7] or ('' if cnt[t] else 'no counted matches')
    tours.append(dict(id=t, src={'cuescore': 'CS', 'epbf': 'EPBF', 'wnt': 'WNT'}.get(r[1], 'TS'), name=r[2], date=r[3], venue=' · '.join(x for x in (r[4], r[5]) if x),
                      game=r[6], matches=cnt[t], players=len(pl[t]), lat=len(pl[t] & LAT), counted=bool(cnt[t]) and not r[7],
                      reason=reason, url=r[8], excluded=str(t) in OV['exclude_tournaments']))
T = {t['id']: t for t in tours}

# ---------- live-scoring check for duplicate pairs ----------
ts_times = collections.defaultdict(list)
for m in raw['matches']:
    if len(m) > 7 and isinstance(m[7], int) and m[7] > 0: ts_times[m[0]].append(m[7])
def cs_fetch(tid):
    try:
        j = requests.get(f'https://api.cuescore.com/tournament/?id={tid}', timeout=40).json()
    except Exception:
        return None
    out = []
    for m in j.get('matches', []) or []:
        x = m.get('stoptime') or m.get('starttime') or ''
        try: out.append(int(datetime.datetime.fromisoformat(x.replace('Z', '+00:00')).timestamp()))
        except Exception: out.append(0)
    return out
fetched = 0
def times(t):
    global fetched
    if T.get(t, {}).get('src') != 'CS': return ts_times.get(t, [])
    if str(t) not in CST and fetched < 30:
        got = cs_fetch(t); fetched += 1; time.sleep(0.5)
        if got is not None: CST[str(t)] = got
    return CST.get(str(t), [])
def live_check(t):
    ev = T.get(t)
    v = [x for x in times(t) if x > 0]
    if not v: return ['none', 'no match times']
    d0 = datetime.datetime.fromisoformat(ev['date']).replace(tzinfo=datetime.timezone.utc).timestamp() if ev else v[0]
    late = (statistics.median(v) - d0) / 86400
    if late > 3: return ['late', f'times {int(late)} days after the event']
    distinct = len({x // 60 for x in v})
    if distinct <= max(2, 0.2 * len(v)): return ['bulk', f'{distinct} different time(s) for {len(v)} matches']
    return ['live', f'{distinct} different times over {round((max(v) - min(v)) / 3600, 1)} h']
for p in DUPS:
    p['check_a'] = live_check(p['a']); p['check_b'] = live_check(p['b'])
json.dump(CST, open('cs_times.json', 'w'), separators=(',', ':'))

out = dict(generated=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), players=players, tournaments=tours, duplicates=DUPS,
           name_review=json.load(open('name_review.json', encoding='utf-8')) if os.path.exists('name_review.json') else [])
os.makedirs('site/admin', exist_ok=True)
s = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
open('site/admin/data.json', 'w', encoding='utf-8').write(s)
print('admin data', len(s), 'bytes', len(players), 'players', len(tours), 'tournaments', len(DUPS), 'duplicate pairs', fetched, 'CueScore time lookups')
