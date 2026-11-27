"""One-off FargoRate lookup (22 Nov 2026) for the Baltic reference-player check: every name in fargo/names.json is searched on
FargoRate's public player search; all profiles with exactly the same name are kept (rating, robustness, id, location)."""
import json, sys, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lookup_core import look
names = json.load(open('fargo/names.json', encoding='utf-8'))
# 27 Nov 2026: names already looked up are kept, only new names (and earlier errors) are searched
try: res = json.load(open('fargo/results.json', encoding='utf-8'))
except Exception: res = {}
todo = [n for n in names if n not in res or res[n] == 'error']
with ThreadPoolExecutor(3) as ex: res.update(dict(ex.map(look, todo)))
json.dump(res, open('fargo/results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(len(todo), 'searched now,', len(names), 'names,', sum(1 for v in res.values() if v and v != 'error'), 'found,', sum(1 for v in res.values() if v == 'error'), 'errors')
