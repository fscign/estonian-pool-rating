"""One-off FargoRate lookup (22 Nov 2026) for the Baltic reference-player check: every name in fargo/names.json is searched on
FargoRate's public player search; all profiles with exactly the same name are kept (rating, robustness, id, location)."""
import json, time, unicodedata, re, requests
from concurrent.futures import ThreadPoolExecutor
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating check)'})
def norm(s):
    s = unicodedata.normalize('NFKD', s or ''); s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace('ø', 'o').replace('ł', 'l').replace('ß', 'ss')
    return ' '.join(sorted(re.sub(r'[^a-z ]', ' ', s).split()))
def look(n):
    for i in range(3):
        try:
            j = S.get('https://dashboard.fargorate.com/api/indexsearch', params={'q': n}, timeout=30).json()
            c = [x for x in j.get('value') or [] if norm((x.get('firstName') or '') + ' ' + (x.get('lastName') or '')) == norm(n)]
            return n, [[int(x.get('rating') or 0), int(x.get('robustness') or 0), x.get('readableId') or '', x.get('location') or ''] for x in c]
        except Exception:
            time.sleep(3)
    return n, 'error'
names = json.load(open('fargo/names.json', encoding='utf-8'))
with ThreadPoolExecutor(4) as ex: res = dict(ex.map(look, names))
json.dump(res, open('fargo/results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(len(names), 'names,', sum(1 for v in res.values() if v and v != 'error'), 'found,', sum(1 for v in res.values() if v == 'error'), 'errors')
