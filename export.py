"""Export SQLite DB into compact JSON for the site."""
import sqlite3, json, collections, datetime
db = sqlite3.connect('ee_pool.sqlite')
# The site gets the Estonians, their opponents, and only the matches and tournaments with an Estonian in them
# (everything else is rated in the background and not needed on the site; keeps data.json small).
SHOWN = {r[0] for r in db.execute('SELECT id FROM players WHERE shown=1')}
EM = [r for r in db.execute('SELECT date, tournament_id, player_a, player_b, score_a, score_b, stage FROM matches ORDER BY date DESC, id DESC') if r[2] in SHOWN or r[3] in SHOWN]
need = SHOWN | {r[2] for r in EM} | {r[3] for r in EM}
players = []
for r in db.execute('''SELECT p.id, p.first_name, p.last_name, p.country, p.city, r.rating, r.racks, r.matches, r.last_played, r.eff_racks, p.ts_id, p.cuescore_id, p.shown, p.sex, p.club
                       FROM players p JOIN ratings r ON r.player_id=p.id ORDER BY r.rating DESC'''):
    if r[0] not in need: continue
    players.append([r[0], r[1], r[2], r[3], r[4], round(r[5], 1), r[6], r[7], r[8], round(r[9]), r[10], r[11], r[12], 1 if r[13] == 'f' else 0, r[14] or ''])
used_t = {r[1] for r in EM}
import re
# short venue names for the site (the same club is written in several ways on the two sites)
VENUE = [(r'bams', 'BAMS'), (r'8\s*ball\s*crew', '8 Ball Crew'), (r'hill\s*hill', 'Hill Hill (EST)'), (r'richi', 'RICHI'),
         (r'champion', "Champion's Club"), (r'break\s*&\s*run', 'Break&Run (EST)'), (r'virtus', 'Virtus'), (r'entry', 'Entry (LIT)'),
         (r'forty\s*3', 'Forty3'), (r'orange bowling', 'Orange Bowling'), (r'krantin', 'Krantinė (LIT)'), (r'olybet.*dole', 'OlyBet Dole'),
         (r'sombrero', 'Sombrero'), (r'baribal', 'Baribal (EST)'), (r'predator.*academy', 'Predator Academy (EST)'), (r'legends', 'Legends'),
         (r'gulb', 'Gulbė (LIT)'), (r'fuksas', 'Fuksas (LIT)'), (r'o[aā]ze', 'Oāze'), (r'kuulsaal', 'Kuulsaal (EST)'), (r'zemgale', 'Zemgale'),
         (r'uptown', 'Uptown (LIT)'), (r'black\s*ball', 'Black Ball (LIT)'), (r'arena riga', 'Arena Riga'), (r'lucky loore', 'Lucky Loore (EST)'),
         (r'club 147', 'Club 147 (EST)')]
def short_place(city, club):
    return re.sub(r'\s*\(EST\)', '', _short_place(city, club)).strip() or 'Estonia'
def _short_place(city, club):
    full = f'{city} {club}'.strip()
    if re.search(r'klondaika', full, re.I):
        town = re.search(r'liep[aā]ja|ventspils|kuld[iī]ga|riga|r[iī]ga', full, re.I)
        return 'Klondaika' + (' ' + town.group(0).capitalize() if town else '')
    if re.search(r'8\s*ball\s*crew', full, re.I) and re.search(r'c[eē]sis', full, re.I): return '8 Ball Crew Cēsis'
    for pat, name in VENUE:
        if re.search(pat, full, re.I): return name
    if full.strip() == '(EST)': return 'Estonia'
    return club or city
tours = []
for r in db.execute('SELECT id, name, date, city, club, game, source, url FROM tournaments WHERE excluded_reason IS NULL ORDER BY date'):
    if r[0] not in used_t: continue
    full = ' · '.join(x for x in (r[3], r[4]) if x)
    tours.append([r[0], r[1], r[2], short_place(r[3] or '', r[4] or ''), '', r[5], r[6], r[7], full])
stage_codes = {}
matches = []
for r in EM:
    st = stage_codes.setdefault(r[6] or '', len(stage_codes))
    matches.append([int(r[0].replace('-', '')), r[1], r[2], r[3], r[4], r[5], st])
hist = collections.defaultdict(dict)
months = sorted({m for (m,) in db.execute('SELECT DISTINCT month FROM rating_history')})
mi = {m: i for i, m in enumerate(months)}
for pid, m, r in db.execute('SELECT player_id, month, rating FROM rating_history'):
    if pid in SHOWN: hist[pid][mi[m]] = int(r)
H = {}
for pid, d in hist.items():
    lo, hi = min(d), max(d)
    H[pid] = [lo] + [d.get(i, 0) for i in range(lo, hi + 1)]   # 0 = gap
out = dict(generated=datetime.date.today().isoformat(), months=months, players=players, tournaments=tours, stages=list(stage_codes), matches=matches, history=H)
s = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
open('site/data.json', 'w').write(s)
print(len(s), 'bytes', len(players), 'players', len(matches), 'matches', len(tours), 'tournaments')
