"""Daily FargoRate lookup (28 Nov 2026): foreign opponents of Estonian players with fewer than 200 racks here, whose names have
not been searched yet, are looked up on FargoRate (at most 150 a day, slowly). Results go to fargo/results.json, which rate.py
uses for the FargoRate pull. Runs after build_db.py; any failure is reported and skipped, the rating still runs."""
import json, sqlite3, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LIMIT = 150
try:
    import requests
    from lookup_core import look
except Exception as e:
    print('FargoRate lookup skipped:', e); sys.exit(0)
db = sqlite3.connect('ee_pool.sqlite')
racks = {}
for a, b, sa, sb, g in db.execute('SELECT player_a, player_b, score_a, score_b, game FROM matches'):
    if g == '14.1': continue
    n = (sa or 0) + (sb or 0); racks[a] = racks.get(a, 0) + n; racks[b] = racks.get(b, 0) + n
q = """SELECT DISTINCT p.id, p.first_name || ' ' || p.last_name FROM matches m
       JOIN players e ON e.id IN (m.player_a, m.player_b) AND e.shown = 1
       JOIN players p ON p.id IN (m.player_a, m.player_b) AND p.id <> e.id
       WHERE p.country NOT IN ('EST', 'LAT', 'LIT')"""
res = json.load(open('fargo/results.json', encoding='utf-8'))
names = json.load(open('fargo/names.json', encoding='utf-8'))
todo = sorted({n.strip() for i, n in db.execute(q) if racks.get(i, 0) < 200 and n.strip() and (n.strip() not in res or res[n.strip()] == 'error')})
print('FargoRate lookup:', len(todo), 'names waiting,', min(len(todo), LIMIT), 'searched now')
found = 0
for n in todo[:LIMIT]:
    _, v = look(n); res[n] = v; found += isinstance(v, list) and any(x[1] >= 200 for x in v)
    if n not in names: names.append(n)
    time.sleep(1)
json.dump(res, open('fargo/results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
json.dump(sorted(names), open('fargo/names.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print('FargoRate lookup: established FargoRate found for', found)
