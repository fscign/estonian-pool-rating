"""FargoRate public player search, shared by lookup.py and daily_lookup.py."""
import json, time, unicodedata, re, requests
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
