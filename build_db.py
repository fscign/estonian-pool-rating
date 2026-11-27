"""Estonian Pool Rating: build the cleaned SQLite DB from the fscign/pool-data files (get_data.sh puts them in data/).
Same rules as the Latvian rating (fscign/latvian-pool-rating build_db.py). Every counted match is rated; only Estonians are shown.
Sources: Tournament Service (Baltic events + any event with an Estonian), CueScore Estonia, Latvia, Lithuania, Finland, Sweden,
Denmark, Norway, EPBF, Matchroom (WNT), PBS. Decided by Aleksandrs 22 Nov 2026."""
import sys
import json, re, sqlite3, collections, unicodedata, datetime, os, gzip

DB = 'ee_pool.sqlite'
def load(f):
    if not os.path.exists(f): print('missing', f); return None
    return json.load(gzip.open(f, 'rt', encoding='utf-8') if f.endswith('.gz') else open(f, encoding='utf-8'))
OV = json.load(open('overrides.json', encoding='utf-8'))   # every manual decision (names, merges, exclusions ...), edited in the admin panel
s = lambda v: v if isinstance(v, str) else ''

# ---------- Tournament Service (all countries in pool-data): Baltic events in full, other countries only with a Baltic player ----------
ts = load('data/ts_raw.json.gz') or {'tournaments': [], 'players': {}, 'matches': []}
P = ts['players']
BALTIC_TS = {'LAT', 'LIT', 'EST', ''}
est_ts = {k for k, v in P.items() if v[2] in ('EST', 'LAT', 'LIT')}   # Baltic calculation (22 Nov 2026): any event with a Baltic player
with_est = {m[0] for m in ts['matches'] if m[2] in est_ts or m[3] in est_ts}
TS_CTRY = {}
d = {'tournaments': [], 'players': P, 'matches': []}
for t in ts['tournaments']:
    cc = t[7] if len(t) > 7 and isinstance(t[7], str) else ''
    if cc in BALTIC_TS or t[0] in with_est:
        d['tournaments'].append(t[:7]); TS_CTRY[t[0]] = cc
keep_ts = set(TS_CTRY)
d['matches'] = [m for m in ts['matches'] if m[0] in keep_ts]
# Tournament Service events only the Latvian repo had (2018 Lithuanian championships and others; pool-data, copied 23 Nov 2026)
_tx = load('data/baltic_extra_ts_raw.json.gz') or {'tournaments': [], 'players': {}, 'matches': []}
_txn = {t[0] for t in _tx['tournaments'] if t[0] not in keep_ts}
for t in _tx['tournaments']:
    if t[0] in _txn: d['tournaments'].append(t[:7]); TS_CTRY[t[0]] = ''
d['matches'] += [m for m in _tx['matches'] if m[0] in _txn]
for k, v in _tx['players'].items(): P.setdefault(k, v)
keep_ts |= _txn

# ---------- CueScore: Baltic and Nordic files from pool-data (tournament rows of collect_cuescore.py) ----------
CS_GAME = {'8-Ball': '8-ball', '9-Ball': '9-ball', '10-Ball': '10-ball', 'Straightpool': 'Straight pool'}
SOURCE = {}            # tournament id -> 'cuescore'
CSIDS = set()          # player ids that come from CueScore
CS_NORDIC = set()      # CueScore profiles seen only in Nordic files: joined to a Tournament Service profile only when the flag matches
CS_ESTONIAN = set(OV.get('estonian', []))
CS_LATVIAN = set(OV.get('latvian', []))      # CueScore profiles with a wrong flag that are Latvian (same list as the Latvian site)    # CueScore profiles with a wrong flag that are Estonian (overrides.json 'estonian')
CS_EXCLUDE = set(OV['exclude_cs_players'])   # CueScore profiles that are not real players
CS_MATCH_OFFSET = 1_000_000_000
for _k in CS_EXCLUDE: P.pop(_k, None)   # not real players, also Tournament Service profiles (e.g. '1 Qualifier', Aleksandrs 22 Nov 2026)
CS_CC = {'LTU': 'LIT', 'GBR': 'ENG', 'DEU': 'GER', 'NLD': 'NED', 'CHE': 'SUI', 'DNK': 'DEN', 'LVA': 'LAT'}   # CueScore codes -> Tournament Service codes
CC_SUFFIX = {'estonia': '', 'latvia': ' (LAT)', 'lithuania': ' (LIT)', 'finland': ' (FIN)', 'sweden': ' (SWE)', 'denmark': ' (DEN)', 'norway': ' (NOR)'}
CLUB = {}              # CueScore id -> club the player represents (collector stores it)
CLUB_MEMBER = {}       # CueScore id -> (club, flag), all collected countries: tells Estonian clubs from foreign ones
T_CTRY = {}            # tournament id -> country code of the venue (for the site)
for cc_file in ('ee', 'lv', 'lt', 'baltic_extra', 'fi', 'se', 'dk', 'no'):   # baltic_extra: BPL Final Vilnius 2025 (organizer without country), POOL8TV 2013-14, 8me 2016
    cs = load(f'data/{cc_file}_cuescore_raw.json.gz')
    if not cs: continue
    nordic = cc_file in ('fi', 'se', 'dk', 'no')
    new_t = set()
    for t in cs['tournaments']:
        tid, name, date, disc, dr, dsets, hc, typ, venue, owner, nm, kept, ctry = t[:13]
        if hc or tid in SOURCE or not date: continue      # handicap tournaments; an event listed in two files counts once
        y, mo, dd = date.split('-')
        d['tournaments'].append([tid, name, f'{dd}.{mo}.{y[2:]}', f"{venue}{CC_SUFFIX.get(ctry, '')}", CS_GAME.get(disc, disc), owner, 0, {}])
        SOURCE[tid] = 'cuescore'; new_t.add(tid); T_CTRY[tid] = ctry
    for cid, v in cs['players'].items():
        fn, ln, cc = v[:3]
        if len(v) > 3 and v[3] and len(v[3]) > 3: CLUB_MEMBER.setdefault(cid, (v[3], cc))
        if cid in CS_EXCLUDE: continue
        if cid in P:
            if not nordic: CS_NORDIC.discard(cid)
            continue
        P[cid] = [ln or '', fn or '', 'EST' if cc == 'EST' or cid in CS_ESTONIAN else 'LAT' if cid in CS_LATVIAN else CS_CC.get(cc, cc or '?'), '', None, 'm']
        CSIDS.add(cid)
        if nordic: CS_NORDIC.add(cid)
        if len(v) > 3 and v[3] and len(v[3]) > 3 and not nordic: CLUB[cid] = (v[5] if len(v) > 5 and v[5] else '', v[3])   # (date, club); alpha3 codes are countries, not clubs
    for x in cs['matches']:
        tid, mid, a, b, sa, sb, race, date, rnd, pen = x[:10]
        if tid not in new_t: continue
        if race and race < 3: continue                   # CueScore stores the race per match
        ts_ = int(datetime.datetime(*map(int, date.split('-')), 12).timestamp()) if date else 0
        d['matches'].append([tid, CS_MATCH_OFFSET + mid, str(a), str(b), str(sa), str(sb), race, ts_, rnd, ''])

# Only Estonian clubs are shown (Aleksandrs 22 Nov 2026): a club counts as Estonian when at least half of its CueScore members
# in all collected countries have the Estonian flag (Stockholms Biljardsällskap, Kville, Vesterålen are not); a player whose
# newest club is foreign has no club on the site
_cm_t, _cm_e = collections.Counter(), collections.Counter()
for _c, _cc in CLUB_MEMBER.values(): _cm_t[_c] += 1; _cm_e[_c] += _cc == 'EST'
EE_CLUB = {c for c in _cm_t if _cm_e[c] * 2 >= _cm_t[c]}
# Newest club read from each Estonian's latest CueScore event (clubs_latest.json, one-time read 22 Nov 2026; the collector keeps
# clubs up to date from then on). For each player the club from the newest event wins.
if os.path.exists('clubs_latest.json'):
    for cid, (day, club) in json.load(open('clubs_latest.json', encoding='utf-8')).items():
        if club and (cid not in CLUB or day >= CLUB[cid][0]): CLUB[cid] = (day, club)

# ---------- EPBF and Matchroom (WNT): all matches; players join others by name and country ----------
EP_T, EP_P, WN_T, WN_P = 6_000_000_000, 6_500_000_000, 5_000_000_000, 5_500_000_000
A2 = dict(lv='LVA', ee='EST', lt='LTU', fi='FIN', se='SWE', no='NOR', dk='DNK', de='DEU', pl='POL', gb='GBR', us='USA', nl='NLD', be='BEL', fr='FRA',
          es='ESP', pt='PRT', it='ITA', at='AUT', ch='CHE', cz='CZE', sk='SVK', hu='HUN', ro='ROU', bg='BGR', gr='GRC', hr='HRV', si='SVN', rs='SRB',
          ba='BIH', al='ALB', xk='XKX', mk='MKD', ua='UKR', by='BLR', ru='RUS', tr='TUR', il='ISR', ie='IRL', ph='PHL', cn='CHN', tw='TWN',
          hk='HKG', jp='JPN', kr='KOR', vn='VNM', id='IDN', my='MYS', sg='SGP', th='THA', au='AUS', nz='NZL', ca='CAN', mx='MEX', ar='ARG',
          br='BRA', cl='CHL', sa='SAU', ae='ARE', kw='KWT', qa='QAT', iq='IRQ', gy='GUY', za='ZAF', ma='MAR', eg='EGY', lu='LUX', me='MNE',
          md='MDA', ge='GEO', am='ARM', az='AZE', kz='KAZ', mt='MLT', cy='CYP', ad='AND', ly='LBY')
A2['is'] = 'ISL'
def cc3(x):
    x = (x or '').strip()
    if len(x) == 2: x = A2.get(x.lower(), '')
    x = x.upper() if len(x) == 3 else ''
    return CS_CC.get(x, x or '?')
EXT_URL = {}
EP_SKIP = re.compile(r'14\.1|14/1|straight|heyball|team|wheelchair|snooker|blackball|doubles|mixed', re.I)
MON = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
ep = load('data/epbf_data.json.gz')
for e in (ep or {}).get('events', []):
    disc = e.get('disc') or ''
    g = re.search(r'\b(8|9|10)-Ball', disc)
    if not g or EP_SKIP.search(disc + ' ' + (e.get('name') or '')) or not e.get('matches'): continue
    try: sd = datetime.datetime.strptime(e['start'], '%b %d, %Y').date()
    except Exception: continue
    tid = EP_T + int(e['id'])
    d['tournaments'].append([tid, f"{e.get('name', '')} \u2013 {disc}", sd.strftime('%d.%m.%y'), '', f"{g.group(1)}-ball", 'EPBF', 0, {}])
    SOURCE[tid] = 'epbf'; EXT_URL[tid] = f"https://www.epbf.com/tournaments/{e.get('ser') or 'eurotour'}/id/{e['id']}/draw-results/"
    ts_ = int(datetime.datetime(sd.year, sd.month, sd.day, 12).timestamp())
    for k, m in enumerate(e['matches']):
        na, ia, fa, sa, sb, nb, ib, fb = m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11]
        if not ia or not ib or not str(sa).isdigit() or not str(sb).isdigit(): continue
        for n, i, f in ((na, ia, fa), (nb, ib, fb)):
            pid = str(EP_P + int(i))
            if pid not in P:
                w = (n or '').split(); sur = [x for x in w if x.upper() == x and re.search(r'[^\W\d_]', x)]; fst = [x for x in w if x not in sur]
                P[pid] = [' '.join(sur), ' '.join(fst), cc3(f), '', None, 'm']
        d['matches'].append([tid, tid * 1000 + k, str(EP_P + int(ia)), str(EP_P + int(ib)), str(sa), str(sb), int(m[3]) if str(m[3]).isdigit() else 0, ts_, m[1], ''])
wn = load('data/wnt_data.json.gz')
WN_IDS = {}
for k_e, e in enumerate(sorted((wn or {}).get('events', []), key=lambda e: e['slug'])):
    if not e['matches']: continue
    m0 = re.match(r'(\w{3}) (\d+)(?: - (?:(\w{3}) )?(\d+))?, (\d{4})', e['date'] or '')
    if not m0: continue
    y = int(m0.group(5)); sd = datetime.date(y, MON[m0.group(1)], int(m0.group(2)))
    tid = WN_T + k_e
    d['tournaments'].append([tid, e['name'], sd.strftime('%d.%m.%y'), e.get('location') or '', '9-ball', 'Matchroom', 0, {}])
    SOURCE[tid] = 'wnt'; EXT_URL[tid] = f"https://www.wntlivescores.com/events/{e['slug']}"
    for k, m in enumerate(e['matches']):
        st, no, rnd, when, tbl, na, fa, sa, sb, nb, fb = m[:11]
        if not str(sa).isdigit() or not str(sb).isdigit() or not na or not nb or 'Wildcard' in na + nb: continue
        w0 = re.match(r'(\w{3}) (\d+)', when or '')
        md = datetime.date(y, MON[w0.group(1)], int(w0.group(2))) if w0 and w0.group(1) in MON else sd
        if md < sd - datetime.timedelta(days=40): md = md.replace(year=y + 1)
        ids = []
        for n, f in ((na, fa), (nb, fb)):
            pid = WN_IDS.setdefault(n, str(WN_P + len(WN_IDS)))
            if pid not in P:
                w = n.split(); P[pid] = [w[-1], ' '.join(w[:-1]), cc3(f), '', None, 'm']
            ids.append(pid)
        race = re.search(r'Race to (\d+)', rnd or '')
        d['matches'].append([tid, tid * 1000 + k, ids[0], ids[1], str(sa), str(sb), int(race.group(1)) if race else 0,
                             int(datetime.datetime(md.year, md.month, md.day, 12).timestamp()), rnd, ''])

# ---------- PBS (Predator Pro Billiard Series): hidden CueScore tournaments, every set is a match ----------
PB_M = 2_000_000_000_000
PB_USE = {'race', 'set', 'set_3_3', 'set_fixed'}
PB_SKIP = re.compile(r'parasport|wheelchair|exhibition|doubles|one ?pocket|bank', re.I)
pb = load('data/pbs_data.json.gz')
for e in (pb or {}).get('events', []):
    g = re.search(r'\b(8|9|10)-Ball', e.get('discipline') or '', re.I)
    tid = int(e['id'])
    if not g or PB_SKIP.search(e.get('name') or '') or tid in SOURCE or not e.get('matches'): continue
    sd = datetime.date.fromisoformat(e['start'][:10])
    d['tournaments'].append([tid, e['name'], sd.strftime('%d.%m.%y'), e.get('venue') or '', f"{g.group(1)}-ball", 'PBS', 0, {}])
    SOURCE[tid] = 'cuescore'
    for m in e['matches']:
        mid, setno, rnd, when, race, ia, na, ca, sa, sb, nb, ib, cb, flag = m[:14]
        if flag not in PB_USE or sa is None or sb is None or not ia or not ib: continue
        for i, n, c in ((ia, na, ca), (ib, nb, cb)):
            i = str(i)
            if i not in P and i not in CS_EXCLUDE:
                w = (n or '').split()
                P[i] = [w[-1] if w else '', ' '.join(w[:-1]), 'EST' if c == 'EST' or i in CS_ESTONIAN else 'LAT' if i in CS_LATVIAN else CS_CC.get(c, c or '?'), '', None, 'm']
                CSIDS.add(i)
        md = datetime.date.fromisoformat(when[:10]) if when else sd
        d['matches'].append([tid, PB_M + int(mid) * 10 + int(setno), str(ia), str(ib), str(sa), str(sb), int(race or 0),
                             int(datetime.datetime(md.year, md.month, md.day, 12).timestamp()), rnd + (f' set {setno}' if setno else ''), ''])

def ph(t):
    t = unicodedata.normalize('NFKD', t.lower()); t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.translate(str.maketrans('аеосрхуі', 'aeocpxyi'))
    t = re.sub(r'[^a-z]', '', t)
    for a, b in [('sch', 's'), ('sh', 's'), ('ch', 'c'), ('zh', 'z'), ('kh', 'h'), ('ts', 'c'), ('y', 'i'), ('j', 'i'), ('w', 'v'), ('ph', 'f')]:
        t = t.replace(a, b)
    t = re.sub(r'(.)\1', r'\1', t)
    return re.sub(r'(s|is|us|a|e|ie|ijs|ij|i)$', '', t)

# ---------- DigitalPool (digitalpool.com): matches of Estonian players abroad, mostly the US (Aleksandrs 27 Nov 2026) ----------
# Only singles of 8, 9, 10-ball and 14.1 with even races. Skipped: test events, team and doubles events, chip tournaments,
# handicap matches (different races), byes, forfeits and unfinished matches, and matches already read from another site
# (Matchroom, EPBF, PBS, CueScore: same two players, same score, within 4 days).
DP_T, DP_P, DP_M = 7_000_000_000, 7_500_000_000, 7_000_000_000_000
DP_GAME = {'EIGHT_BALL': '8-ball', 'NINE_BALL': '9-ball', 'TEN_BALL': '10-ball', 'STRAIGHT_POOL': 'Straight pool'}
DP_TEST = re.compile(r'\btest|tester|fddf|newest one|grgrg|^how$|sun346|bracket \d+$|temp$|giải 128|mosconi cup|thirty thirsday', re.I)
DP_CC = {'estonia': 'EST', 'latvia': 'LAT', 'lithuania': 'LTU', 'finland': 'FIN', 'united states': 'USA', 'usa': 'USA', 'germany': 'GER',
         'spain': 'ESP', 'austria': 'AUT', 'saudi arabia': 'SAU', 'philippines': 'PHI', 'poland': 'POL', 'netherlands': 'NED', 'canada': 'CAN'}
dp = load('data/digitalpool_raw.json.gz')
if dp:
    import json as _json
    _ds = _json.load(open('data/digitalpool_search.json', encoding='utf-8')) if os.path.exists('data/digitalpool_search.json') else {'names': []}
    DP_EE = {ph(n) for n, _f, _l in _ds['names']} | {ph(' '.join(n.split()[::-1])) for n, _f, _l in _ds['names']}
    def _pname(i): v = P.get(i); return ph(f"{v[1]} {v[0]}") if v else ''
    _seen = {}
    for m in d['matches']:
        if not str(m[4]).isdigit() or not str(m[5]).isdigit(): continue
        _seen.setdefault((frozenset((_pname(m[2]), _pname(m[3]))), tuple(sorted((int(m[4]), int(m[5]))))), []).append(m[7])
    DP_IDS = {}
    def dp_player(name, flag):
        name = re.sub(r'\s+', ' ', name or '').strip()
        if name.isupper() or name.islower(): name = name.title()
        key = ph(name)
        pid = DP_IDS.setdefault(key, str(DP_P + len(DP_IDS)))
        if pid not in P:
            w = name.split(); f = (flag or '').strip()
            cc = 'EST' if key in DP_EE else (DP_CC.get(f.lower()) or (cc3(f) if len(f) in (2, 3) else '?'))
            P[pid] = [w[-1], ' '.join(w[:-1]), cc, '', None, 'm']
        return pid
    dp_n = dp_dup = 0
    by_t = {}
    for mid, m in dp['matches'].items(): by_t.setdefault(str(m[0]), []).append((int(mid), m))
    for tk, ms in by_t.items():
        t = dp['tournaments'].get(tk)
        if not t: continue
        name, start, gtype, ttype, vname, vcc, is_test, hc = t[:8]; slug = t[8] if len(t) > 8 else ''
        if is_test or DP_TEST.search((name or '').strip()) or gtype not in DP_GAME or ttype == 'chip' or not start: continue
        if re.search(r'scotch|doubles|team|world cup of pool', name or '', re.I): continue
        sd = datetime.date.fromisoformat(start)
        tid = DP_T + int(tk); added = False
        for mid, m in sorted(ms):
            _, rnd, no, n1, f1, s1, r1, x1, n2, f2, s2, r2, x2, bye, st, when = m
            if bye or st != 'COMPLETED' or x1 or x2 or s1 is None or s2 is None or not n1 or not n2: continue
            if re.search(r'\bbye\b|/|&|\d', n1 + ' ' + n2, re.I) or len(n1.split()) < 2 or len(n2.split()) < 2: continue   # placeholders, teams
            if (r1 or 0) != (r2 or 0) or max(s1, s2) <= 0: continue      # handicap (different races) or empty
            race = r1 or 0
            if race and max(s1, s2) != race: continue                   # not finished
            md = datetime.date.fromisoformat(when) if when else sd
            ts_ = int(datetime.datetime(md.year, md.month, md.day, 12).timestamp())
            a, b = dp_player(n1, f1), dp_player(n2, f2)
            k = (frozenset((_pname(a), _pname(b))), tuple(sorted((int(s1), int(s2)))))
            if any(abs(ts_ - x) <= 4 * 86400 for x in _seen.get(k, [])): dp_dup += 1; continue
            _seen.setdefault(k, []).append(ts_)
            if not added:
                d['tournaments'].append([tid, (name or '').strip(), sd.strftime('%d.%m.%y'), ' · '.join(x for x in (vname, vcc) if x), DP_GAME[gtype], 'DigitalPool', 0, {}])
                SOURCE[tid] = 'digitalpool'; EXT_URL[tid] = f"https://digitalpool.com/tournaments/{slug}" if slug else "https://digitalpool.com/tournaments"; added = True
            d['matches'].append([tid, DP_M + mid, a, b, str(s1), str(s2), race, ts_, f"round {rnd}", ''])
            dp_n += 1
    print(f'DigitalPool: {dp_n} matches added, {dp_dup} already read from another site')

# ---------- profile merges (alias -> canonical tournamentservice id) ----------
MANUAL_MERGES = [[m['keep'], m['merge']] for m in OV['merges'] if m.get('stage') == 'manual']
EXCLUDE_PLAYERS = set(OV['exclude_players'])   # rated in the background, not shown
NAME_OVERRIDE = {}   # names now come from overrides.json 'names' (see display())
NOT_SAME = {frozenset(x['ids']) for x in OV['not_same']}   # different people, never merge
MATCH_FIX = {int(k): (tuple(v['score']) if v['score'] is not None else None) for k, v in OV['match_fix'].items()}   # single matches: corrected score, or None = not played

def ph(t):
    t = unicodedata.normalize('NFKD', t.lower()); t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.translate(str.maketrans('аеосрхуі', 'aeocpxyi'))
    t = re.sub(r'[^a-z]', '', t)
    for a, b in [('sch', 's'), ('sh', 's'), ('ch', 'c'), ('zh', 'z'), ('kh', 'h'), ('ts', 'c'), ('y', 'i'), ('j', 'i'), ('w', 'v'), ('ph', 'f')]:
        t = t.replace(a, b)
    t = re.sub(r'(.)\1', r'\1', t)
    return re.sub(r'(s|is|us|a|e|ie|ijs|ij|i)$', '', t)

def is_person(v):
    return (v and v[5] in ('m', 'f') and s(v[0]) and s(v[1]) and 'izloze' not in (s(v[0]) + s(v[1])).lower()
            and '/' not in s(v[0]) + s(v[1]) and not s(v[0]).lower().startswith(('dbl', 'trpl')))

# ---------- tournaments ----------
# BPL MINI events checked on CueScore (description / handicap setting): 2024-2025 MINIs were played without handicap
MINI_NO_HCP = {int(k) for k in OV['not_handicap']}
TEAM_EVENT = re.compile(r'komand|\bteam\b', re.I)   # team championships: results inside are unreliable (decided 2026-10-23)
EXCLUDE_TOURNAMENTS = {int(k): v['reason'] for k, v in OV['exclude_tournaments'].items()}   # never counted, even when the update fetches them again
PAIR = re.compile(r'pār|paru|pair|dubult|parn|mix ?pār|paar|porų|poros|doubles|dvejet', re.I)   # pair events (EE 'paar', LT 'porų', EN 'doubles' added 2026-11-10)
EXCL_NAME = re.compile(r'bank ?pool|one ?pocket|hcp|handi?cap|handikap|фора|marat|sn[uū]k|snooker', re.I)
def name_hcp(n, org='', date=None):   # handicap by name or organizer rule (Baribal Monday, Baribal HC, 'fora', Hill Hill Mondays): rules/score_rules.py in pool-data
    sys.path.insert(0, 'data'); import score_rules; return score_rules.name_handicap(n, org, date)
def game_of(t):
    disc, name = t[4], t[1]
    if re.search(r'8\s*/\s*9\s*/\s*10|8910|pool9-pool8-pool10|p8/9/10', name, re.I): return 'mixed'
    # 14.1 counts since 2 Nov 2026 (points / 14 = racks in rate.py)
    if disc in ('Straight pool', 'Puls14+1', 'Straightpool'): return '14.1'
    if disc in ('Pool', 'all-around pool', '') and re.search(r'14\s*[.+]\s*1|straight|pulas-14|pool-?14', name, re.I) and not re.search(r'pulas-?(8|9|10)\b|pool-?(8|9|10)\b', name, re.I): return '14.1'
    # the game written in the name wins over a generic or wrong TS discipline ('Lietuvos Moterų Pulo ČEMPIONATAS 21: Pulas-8'
    # is stored as all-around pool, 'Lietuvos pulas-8 čempionatas' 2014 as 9-ball; 23 Nov 2026, as the Latvian data has them)
    _g = re.search(r'\bpulas[- ]?(8|9|10)\b', name, re.I)
    if _g and disc not in ('Straight pool', 'Puls14+1', 'Straightpool'): return f'{_g.group(1)}-ball'
    if disc in ('8-ball', 'Puls8', 'Puls 8', 'Пул 8', 'Pulas-8', 'Aštuonukė'): return '8-ball'
    if disc in ('9-ball', 'Puls9', 'Devyniukė', 'Пул 9', 'Pulas-9'): return '9-ball'
    if disc in ('10-ball', 'Puls10', 'Пул 10', 'Pulas-10', 'Dešimtukė'): return '10-ball'
    # Sigulda weekly events with discipline 'Pool' (game not stated on TS) count, decided 31 Oct 2026
    if disc == 'Pool' and re.search(r'sigu\w*das? b\w+ čempionāts', name, re.I): return 'pool'
    if disc in ('Pool', 'all-around pool'): return 'mixed'
    return None

def parse_date(ddmmyy):
    dd, mm, yy = ddmmyy.split('.')
    return datetime.date(2000 + int(yy), int(mm), int(dd))

T = {}
for t in d['tournaments']:
    tid, name, date, place, disc, org = t[:6]
    name = re.sub(r'^[2-6](?=[A-ZĀČĒĢĪĶĻŅŠŪŽ])', '', name)   # stray digit from the site's icon markup
    g = game_of(t)
    excl = None
    plain = ''.join(c for c in unicodedata.normalize('NFKD', name.lower()) if not unicodedata.combining(c))
    if PAIR.search(name): excl = 'doubles'
    elif TEAM_EVENT.search(name): excl = 'team event'
    # Sigulda weekly championship is included (decided 2026-10-17)
    elif tid in EXCLUDE_TOURNAMENTS: excl = EXCLUDE_TOURNAMENTS[tid]
    elif EXCL_NAME.search(name): excl = 'other discipline'
    elif name_hcp(name, org, parse_date(date) if date else None): excl = name_hcp(name, org, parse_date(date) if date else None)
    elif re.search(r'\bmini\b', name, re.I) and tid not in MINI_NO_HCP: excl = 'BPL MINI division (played with handicap)'
    elif g is None: excl = 'other discipline'
    elif g == 'mixed': excl = 'mixed 8/9/10 or unknown game'
    city, club = (place.split('БК «') + [''])[:2] if 'БК «' in place else (place, '')
    city = city.replace('г. ', '').strip(); club = club.replace('»', '').strip()
    if 'клуб не назначен' in city: city = city.replace('клуб не назначен', '').strip()
    T[tid] = dict(id=tid, name=name, date=parse_date(date), city=city, club=club, disc=disc, game=g, org=org, excl=excl)

# ---------- valid matches (before player filtering) ----------
def score(x):
    try: a, b = int(x[4]), int(x[5])
    except ValueError: return None
    if a < 0 or b < 0 or (a == 0 and b == 0): return None   # forfeits (0:-1) and unplayed
    if max(a, b) < 3: return None   # races shorter than 3 are not rated (races to 3 count since 26 Oct 2026)
    return a, b

# A long match inside a round that was otherwise played to 2-3 is a typo (e.g. one 4:1 among race-to-3 group games).
# Keep long matches only when at least half of the played matches in the same round/stage are long too
# (so a longer final, semifinals or play-off rounds still count). Tournament Service only: CueScore stores the race per match.
def played(x):
    try: a, b = int(x[4]), int(x[5])
    except ValueError: return None
    return None if a < 0 or b < 0 or a + b == 0 else max(a, b)
stage_all, stage_long = collections.Counter(), collections.Counter()
for x in d['matches']:
    if x[0] in SOURCE: continue
    w = played(x)
    if w is None: continue
    stage_all[(x[0], x[8])] += 1
    if w >= 3: stage_long[(x[0], x[8])] += 1
# Score and event rules shared by every rating: rules/score_rules.py in fscign/pool-data, downloaded by get_data.sh
# (walkovers written as a score, short scores raised to the race, odd-format and test/money events; Aleksandrs 22-23 Nov 2026)
sys.path.insert(0, 'data')
import score_rules as SR
TSMAX = 1_000_000   # Tournament Service event ids are small; TS stores a reliable race for each match
_ev = {}
for x in d['matches']:
    t = T[x[0]]
    if t['excl'] or t['game'] == '14.1': continue
    sc = score(x)
    if sc: _ev.setdefault(x[0], {'name': t['name'], 'per_match_race': x[0] < TSMAX or SOURCE.get(x[0]) == 'digitalpool', 'matches': []})['matches'].append((x[1], x[8], x[6], sc))
RULES = SR.ScoreRules(_ev, OV.get('format_ok', {}))
ODD_EVENTS = RULES.odd_events
for tid, why in ODD_EVENTS.items(): T[tid]['excl'] = why
WALKOVER_EX = []; FIXED_EX = []; SHORT_EX = []
odd_long = collections.Counter()
raw_valid = []
for x in d['matches']:
    t = T[x[0]]
    if t['excl']: continue
    sc = score(x)
    if not sc: continue
    fx = next((MATCH_FIX[i] for i in (x[1], x[1] + CS_MATCH_OFFSET) if i in MATCH_FIX), False)
    if fx is None: continue
    if fx: sc = fx
    if t['game'] == '14.1' and max(sc) < 50: continue   # straight pool: matches to 50 points or longer only (Aleksandrs 20 Nov 2026)
    if t['game'] != '14.1' and not fx:
        act, new_sc, race, how = RULES.decide(x[0], x[1], x[8], x[6], sc)
        if act != 'keep':
            info = dict(tid=x[0], mid=x[1], a=x[2], b=x[3], score=sc, race=race, own=x[6], stage=x[8], how=how)
            if act == 'fix': sc = new_sc; info['new'] = sc; FIXED_EX.append(info)
            elif act == 'walkover': WALKOVER_EX.append(info); continue
            else: SHORT_EX.append(info)
    k = (x[0], x[8])
    if x[0] not in SOURCE and t['game'] != '14.1' and stage_long[k] < 0.5 * stage_all[k]:
        odd_long[x[0]] += 1; continue
    a, b = x[2], x[3]
    if a == b or not is_person(P.get(a)) or not is_person(P.get(b)): continue
    ts = x[7]
    md = datetime.datetime.utcfromtimestamp(ts).date() if ts else t['date']
    if abs((md - t['date']).days) > 20: md = t['date']
    raw_valid.append(dict(tid=x[0], mid=x[1], a=a, b=b, sa=sc[0], sb=sc[1], race=x[6], date=md, stage=x[8]))

# ---------- canonical player mapping ----------
cnt = collections.Counter()
for m in raw_valid: cnt[m['a']] += 1; cnt[m['b']] += 1
canon = {}
def find(k):
    while canon.get(k, k) != k: k = canon[k]
    return k
# Player ids already on the site keep their id when profiles are merged, so page links never break
try: KEEP_IDS = {str(p[0]) for p in json.load(open('site/data.json', encoding='utf-8'))['players']}
except Exception: KEEP_IDS = set()
NS = collections.defaultdict(set)   # 'never merge' partners (overrides.json 'not_same'); checked at every merge
for x in OV['not_same']:
    a_, b_ = (str(i) for i in x['ids']); NS[a_].add(b_); NS[b_].add(a_)
members = {}
def union(ids):
    roots = sorted({find(k) for k in ids}, key=lambda k: (k not in KEEP_IDS, -cnt[k], int(k)))   # fixed order, so ids stay the same between runs
    for r in roots[1:]:
        A, B = members.get(roots[0], {roots[0]}), members.get(r, {r})
        if any(NS[x] & B for x in A): continue   # Aleksandrs marked two of these profiles as different people
        canon[r] = roots[0]; members[roots[0]] = A | B
groups = collections.defaultdict(list)
for k, v in P.items():
    if is_person(v) and cnt[k] and k not in CSIDS:
        groups[(v[2] or '?',) + tuple(sorted([ph(s(v[0])), ph(s(v[1]))]))].append(k)
for ids in groups.values():
    if len(ids) > 1 and frozenset(ids) not in NOT_SAME: union(ids)
for ids in MANUAL_MERGES: union(ids)

# CueScore profiles -> Tournament Service players (exact name match, or confirmed by Aleksandrs)
CS_MANUAL = {cs: v['ts'] for cs, v in OV['cs_links'].items()}   # CueScore profile -> Tournament Service profile
# Challonge 2015/16 events: their player ids that belong to existing players (challonge_events.json)
if os.path.exists('challonge_events.json'): CS_MANUAL.update(json.load(open('challonge_events.json', encoding='utf-8'))['manual'])
def attach(cid, ts):
    a, b = find(ts), find(cid)        # Tournament Service profile stays the main one
    if a == b: return
    A, B = members.get(a, {a}), members.get(b, {b})
    if any(NS[x] & B for x in A): return
    canon[b] = a; members[a] = A | B
ts_index = collections.defaultdict(list)
for k, v in P.items():
    if k not in CSIDS and is_person(v): ts_index[tuple(sorted([ph(s(v[0])), ph(s(v[1]))]))].append(k)
cs_new = collections.defaultdict(list)
for cid in sorted(CSIDS, key=int):
    v = P[cid]
    if cid in CS_MANUAL: attach(cid, CS_MANUAL[cid]); continue
    key = tuple(sorted([ph(s(v[0])), ph(s(v[1]))]))
    hits = ts_index.get(key, [])
    if cid in CS_NORDIC: hits = [k for k in hits if P[k][2] == v[2]]   # Nordic-only profiles: same name AND same flag
    if hits:
        roots = sorted({find(k) for k in hits}, key=lambda r: (-cnt[r], int(r)))
        attach(cid, roots[0])
    elif is_person(v): cs_new[(v[2],) + key].append(cid)
for ids in cs_new.values():
    if len(ids) > 1: union(ids)
# confirmed by Aleksandrs 2026-10-18 (player check list); ids are the merged player ids, any source
LATE_MERGES = [[m['keep'], m['merge']] for m in OV['merges'] if m.get('stage', 'late') == 'late']
# race-to-3 player check (Aleksandrs, 23 Oct 2026)
NAME_FILE = {k: (v['first'], v['last']) for k, v in OV['names'].items()}   # confirmed names, shown exactly as written (overrides.json 'names')
# Latvian spelling of Tournament Service names (update.py reads them with Accept-Language: lv for new players)
P_LV = d.get('players_lv', {})
NAME_REVIEW = []   # Latvian TS name differs in more than letters from the English one: keep the current name, Aleksandrs decides
for ids in LATE_MERGES: union(ids)
C = lambda k: find(k)

# ---------- everyone in the counted events is rated; only Latvians are shown on the site ----------
def country(k): return P[k][2]
eligible = set(C(k) for k in cnt)
SHOWN = {k for k in eligible if country(k) == 'EST' and k not in EXCLUDE_PLAYERS}
# players with another flag who play in Estonia and are shown (overrides 'estonian', any profile id; Aleksandrs 22 Nov 2026:
# Phil Mathias, Michael Kirsch, Anton Bobkov)
FORCE_EST = {C(k) for k in OV.get('estonian', []) if k in P and C(k) in eligible}
FORCE_LAT = {C(k) for k in OV.get('latvian', []) if k in P and C(k) in eligible}
SHOWN |= {k for k in FORCE_EST if k not in EXCLUDE_PLAYERS}

# ---------- final matches; a tournament entry that repeats another entry (>=50% same results) is a duplicate ----------
def rkey(m, a, b): return tuple(sorted([(a, m['sa']), (b, m['sb'])]))
cand = []
for m in sorted(raw_valid, key=lambda m: (m['date'], m['tid'], m['mid'])):
    a, b = C(m['a']), C(m['b'])
    if a in eligible and b in eligible and a != b: cand.append((m, a, b))
by_t = collections.defaultdict(set)
for m, a, b in cand: by_t[m['tid']].add(rkey(m, a, b))
dup_of = {}
# fixed choices from the admin panel (overrides.json 'duplicates': copy id -> original id); the automatic rule only decides the other pairs
FORCED = {int(c): int(v['original']) for c, v in OV.get('duplicates', {}).items()}
FORCED_IDS = set(FORCED) | set(FORCED.values())
tids = sorted(by_t)
for i, t1 in enumerate(tids):
    for t2 in tids[i + 1:]:
        if t1 in FORCED_IDS and t2 in FORCED_IDS: continue
        dd = abs((T[t1]['date'] - T[t2]['date']).days)
        ov = len(by_t[t1] & by_t[t2])
        if not ov: continue
        sm = min(len(by_t[t1]), len(by_t[t2]))
        # close dates: half the results the same is enough; any distance (an event re-entered weeks later): 5+ same results and 90% of the smaller entry
        if (dd <= 3 and ov >= 0.5 * sm) or (dd <= 14 and ov >= 5 and ov >= 0.5 * sm) or (ov >= 5 and ov >= 0.9 * sm):
            dup_of[t2] = t1
dup_of.update({c: o for c, o in FORCED.items() if c in by_t})
DUPLICATE_ENTRIES = {t2: t1 for t2, t1 in dup_of.items()}
matches = []
for m, a, b in cand:
    if m['tid'] in DUPLICATE_ENTRIES: continue   # the whole event is a copy of another entry; keep only the original
    matches.append(dict(m, a=a, b=b))
print('duplicate entries', [(T[t2]['name'], T[t1]['name']) for t2, t1 in DUPLICATE_ENTRIES.items()])

# team events: keep their singles only when there are enough of them to mean something
TEAM = re.compile(r'koman|team', re.I)
per_t = collections.Counter(m['tid'] for m in matches)
small_team = {t for t, n in per_t.items() if TEAM.search(T[t]['name']) and n < 10}
for t in small_team: T[t]['excl'] = 'team event, fewer than 10 matches'
matches = [m for m in matches if m['tid'] not in small_team]
used = collections.Counter()
for m in matches: used[m['a']] += 1; used[m['b']] += 1

# ---------- write SQLite ----------
if os.path.exists(DB): os.remove(DB)
db = sqlite3.connect(DB)
db.executescript('''
CREATE TABLE players(id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, country TEXT, city TEXT, birth TEXT, sex TEXT,
  ts_id INTEGER, cuescore_id INTEGER, fargo_id INTEGER, shown INTEGER, club TEXT, league TEXT, sex_hint TEXT);
CREATE TABLE player_profiles(source TEXT, source_id TEXT, player_id INTEGER, name_on_source TEXT, PRIMARY KEY(source, source_id));
CREATE TABLE tournaments(id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, name TEXT, date TEXT, city TEXT, club TEXT,
  game TEXT, discipline_raw TEXT, organizer TEXT, excluded_reason TEXT, url TEXT);
CREATE TABLE matches(id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, tournament_id INTEGER, date TEXT, stage TEXT, race_to INTEGER,
  player_a INTEGER, player_b INTEGER, score_a INTEGER, score_b INTEGER, game TEXT);
CREATE TABLE ratings(player_id INTEGER PRIMARY KEY, rating REAL, racks INTEGER, eff_racks REAL, matches INTEGER, last_played TEXT, rank INTEGER);
CREATE TABLE rating_history(player_id INTEGER, month TEXT, rating REAL, PRIMARY KEY(player_id, month));
''')
TRL = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя', 'a b v g d e jo zh z i j k l m n o p r s t u f h c ch sh shch _ y _ e ju ja'.split()))
def translit(t):
    out = ''.join(TRL.get(ch.lower(), ch) for ch in t).replace('_', '')
    return out[:1].upper() + out[1:]
LOOK = str.maketrans('АаВЕеКМНОоРрСсТуХх', 'AaBEeKMHOoPpCcTyXx')   # Cyrillic look-alike letters inside Latin names
CYR = re.compile('[А-Яа-яЁё]')
last_seen = {}
for m in raw_valid:
    for p in (m['a'], m['b']): last_seen[p] = max(last_seen.get(p, m['date']), m['date'])
group = collections.defaultdict(list)
for k in P:
    if is_person(P[k]) and C(k) in used: group[C(k)].append(k)
def cap(x):   # every part of a name: first letter capital, the rest small ("MIKHAIL" -> "Mikhail", "Rolle-sarkans" -> "Rolle-Sarkans")
    x = x.strip(' .')
    return ' '.join('-'.join(w[:1].upper() + w[1:].lower() for w in part.split('-')) for part in x.split())
def fold_name(x):
    x = unicodedata.normalize('NFD', x.lower()); x = ''.join(c for c in x if not unicodedata.combining(c))
    return re.sub(r'[^a-z]', '', x.replace('sh', 's').replace('ch', 'c').replace('zh', 'z'))
def display(root):
    for k in group[root]:
        if k in NAME_FILE: return NAME_FILE[k]   # confirmed spelling, exactly as given (no cap())
    f, l = display_raw(root); return cap(f), cap(l)
def display_raw(root):
    for k in group[root]:
        if k in NAME_OVERRIDE: return NAME_OVERRIDE[k]
    latin = [k for k in group[root] if not CYR.search(s(P[k][0]) + s(P[k][1]))]
    cands = [k for k in latin if k not in CSIDS] or latin or group[root]   # prefer Tournament Service spelling
    best = max(cands, key=lambda k: last_seen.get(k, datetime.date.min))
    f, l = s(P[best][1]), s(P[best][0])
    lv = P_LV.get(best)
    if lv and (s(lv[0]), s(lv[1])) != (l, f):
        if fold_name(s(lv[1]) + s(lv[0])) == fold_name(f + l): f, l = s(lv[1]), s(lv[0])   # same name, Latvian letters
        else: NAME_REVIEW.append((best, f'{f} {l}', f'{s(lv[1])} {s(lv[0])}'))
    # Estonian site: the same name with Estonian letters (õ ä ö ü š ž) wins, from any profile (often CueScore)
    nonascii = lambda x: sum(1 for c in x if ord(c) > 127)
    for k in group[root]:
        f3, l3 = s(P[k][1]), s(P[k][0])
        if not CYR.search(f3 + l3) and fold_name(f3 + l3) == fold_name(f + l) and nonascii(f3 + l3) > nonascii(f + l): f, l = f3, l3
    f2, l2 = f.translate(LOOK), l.translate(LOOK)
    if not CYR.search(f2 + l2): return f2, l2
    return translit(f), translit(l)
# Men / women: a woman's profile on Tournament Service, or a female Latvian name (first name and surname both end in -a/-e)
MALE_A = {'ivica', 'nikola', 'luka', 'mika', 'juha', 'jukka', 'joona', 'joosua', 'aleksa', 'jaška', 'jaska', 'nikita', 'ilja', 'ilya', 'kostja', 'sasha', 'sasa', 'misha', 'misa', 'danila', 'vova', 'andrea', 'luca', 'jura', 'kolja', 'tolja', 'vanja', 'gena', 'zhenja', 'zenja'}
SEX_OVERRIDE = dict(OV['sex'])
# Estonian female first names that do not end in -a (add more in overrides 'sex' from the admin panel)
FEMALE_EE = {'kart', 'liis', 'liisi', 'liise', 'heidy', 'heidi', 'kristel', 'kristi', 'kristin', 'kristiina', 'annika', 'elo', 'kullike',
             'lotte', 'lisette', 'michelle', 'mari', 'marie', 'merle', 'merli', 'merilin', 'kerli', 'kelly', 'kairi', 'kadri', 'kai', 'kati',
             'katrin', 'karin', 'kadi', 'piret', 'reet', 'sirje', 'triin', 'triinu', 'ulle', 'ly', 'anne', 'anni', 'eve', 'ene', 'helen',
             'helle', 'ingrid', 'birgit', 'getter', 'grete', 'gerli', 'elis', 'elise', 'eliise', 'jane', 'janne', 'kaire', 'kaisa', 'kertu',
             'kirke', 'laura', 'liina', 'maarja', 'marju', 'mirjam', 'pille', 'riin', 'siiri', 'signe', 'sigrid', 'tiiu', 'urve', 'viivi',
             'evelin', 'evelyn', 'karmen', 'kerttu', 'marit', 'merit', 'piia', 'raili', 'sandra', 'sille', 'stella', 'terje', 'tuuli',
             'vivian', 'yvonne', 'iris', 'irene', 'alice', 'agnes', 'ester', 'ruth', 'olga', 'karoliine', 'kristel-ly', 'emma', 'mia'}
def plain(x): return ''.join(c for c in unicodedata.normalize('NFKD', x.lower()) if not unicodedata.combining(c)).strip()
# Women (Aleksandrs 22 Nov 2026): players who played a women's event (Naisteliiga, Eesti MV naised, BPL / Latvian / Lithuanian /
# EPBF / Nordic women's events); anyone else only by hand (overrides 'sex'). Name rules below are only a hint for the review list.
WOMEN_EV = re.compile(r'naiste|naised|\bwomen|\bladies|sieviet|moter|\bdamen|\bnaiset|\bnaisten|\bdam(?:er|or)\b|female', re.I)
MIXED_EV = re.compile(r'senior|veteran|meistar|oldboy|&', re.I)
women_t = {t[0] for t in d['tournaments'] if WOMEN_EV.search(s(t[1])) and not MIXED_EV.search(s(t[1]))}
women_p = set()
for m in d['matches']:
    if m[0] in women_t: women_p.update((m[2], m[3]))
SEX_HINT = {}   # player -> 'f' by the old name rule, for the review list
def sex_of(k, first, last):
    if k in SEX_OVERRIDE: return SEX_OVERRIDE[k]
    if any(x in women_p for x in group[k]): return 'f'
    SEX_HINT[k] = sex_by_name(k, first, last)
    return 'm'
def sex_by_name(k, first, last):
    if any(P[x][5] == 'f' and x not in CSIDS for x in group[k]): return 'f'
    f = (plain(first).replace('-', ' ').split() or [''])[0]; l = plain(last)
    if country(k) in ('LAT', 'LIT'):   # Latvian / Lithuanian names: first name and surname both end in -a/-e
        return 'f' if f[-1:] in ('a', 'e') and f not in MALE_A and l[-1:] in ('a', 'e') else 'm'
    # Estonian and other names (22 Nov 2026: Rene Kivila, Andre Kiholane came out as women with the Latvian rule):
    # the surname says nothing; a first name ending in -a is female (except known male names), else only known female names
    if f in FEMALE_EE: return 'f'
    return 'f' if f[-1:] == 'a' and f not in MALE_A else 'm'
# ---------- skill league (federation list, leagues.json; anyone not listed is Rahvaliiga) ----------
LG = json.load(open('leagues.json', encoding='utf-8')) if os.path.exists('leagues.json') else {}
LG_FOLD, LG_PH = {}, {}
for code in ('ML', 'EL', 'TL'):
    for n in LG.get(code, []):
        LG_FOLD[fold_name(n)] = code
        w = n.split(); LG_PH[tuple(sorted([ph(w[0]), ph(w[-1])]))] = code
LG_FOUND = set()
LG_OVERRIDE = OV.get('league', {})   # player id -> ML/EL/TL/RL, for players missing from the federation list or listed wrongly
def league_of(k, first, last):
    for x in group[k]:
        if x in LG_OVERRIDE: return LG_OVERRIDE[x]
    names = [(first, last)] + [(s(P[x][1]), s(P[x][0])) for x in group[k]]
    for f_, l_ in names:
        c = LG_FOLD.get(fold_name(f_ + l_)) or LG_PH.get(tuple(sorted([ph((f_.split() or [''])[0]), ph((l_.split() or [''])[-1])])))
        if c: LG_FOUND.add(c + ':' + f_ + ' ' + l_); return c
    return 'RL'
for k in sorted(used, key=int):
    v = P[k]; first, last = display(k)
    v = list(v); v[5] = sex_of(k, first, last)
    if v[2] in ('', '?', 'TBA', None):   # placeholder country on the main profile: take the one from another merged profile
        cc_ = collections.Counter(P[x][2] for x in group[k] if P[x][2] not in ('', '?', 'TBA', None))
        if cc_: v = list(v); v[2] = cc_.most_common(1)[0][0]
    city = next((s(P[x][3]) for x in sorted(group[k], key=lambda x: -cnt[x]) if s(P[x][3])), '')
    birth = next((s(P[x][4]) for x in sorted(group[k], key=lambda x: -len(s(P[x][4]))) if s(P[x][4])), '')
    cs_id = next((int(x) for x in group[k] if x in CSIDS), None)
    ts_id = int(k) if k not in CSIDS else None
    clubs = sorted(CLUB[x] for x in group[k] if x in CLUB)   # newest club the player represented on CueScore
    if k in FORCE_EST: v = list(v); v[2] = 'EST'
    if k in FORCE_LAT: v = list(v); v[2] = 'LAT'
    lg = league_of(k, first, last) if k in SHOWN else None
    db.execute('INSERT INTO players VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)', (int(k), first, last, v[2], city, birth, v[5], ts_id, cs_id, int(k in SHOWN),
               clubs[-1][1] if clubs and clubs[-1][1] in EE_CLUB else None, lg, SEX_HINT.get(k)))
for k, v in P.items():
    if is_person(v) and C(k) in used:
        db.execute('INSERT INTO player_profiles VALUES(?,?,?,?)', ('cuescore' if k in CSIDS else 'tournamentservice', k, int(C(k)), f'{s(v[1])} {s(v[0])}'))
for t in T.values():
    src = SOURCE.get(t['id'], 'tournamentservice')
    url = EXT_URL.get(t['id']) or (f"https://cuescore.com/tournament/x/{t['id']}" if src == 'cuescore' else f"https://tournamentservice.net/tournament.php?finstand={t['id']}")
    excl = t['excl'] or ('duplicate of ' + str(DUPLICATE_ENTRIES[t['id']]) if t['id'] in DUPLICATE_ENTRIES and not any(m['tid'] == t['id'] for m in matches) else None)
    db.execute('INSERT INTO tournaments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (t['id'], src, str(t['id']), t['name'], t['date'].isoformat(),
               t['city'], t['club'], t['game'], t['disc'], t['org'], excl, url))
for m in matches:
    msrc = SOURCE.get(m['tid'], 'tournamentservice')
    db.execute('INSERT INTO matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (m['mid'], msrc, str(m['mid'] - CS_MATCH_OFFSET if msrc == 'cuescore' else m['mid']), m['tid'], m['date'].isoformat(), m['stage'],
               int(m['race']) if str(m['race']).isdigit() else None, int(m['a']), int(m['b']), m['sa'], m['sb'], T[m['tid']]['game']))
db.commit()
print('tournaments total', len(T), 'used', len({m['tid'] for m in matches}))
print('excluded', collections.Counter(t['excl'] for t in T.values()))
print('odd-format events not counted:', len(ODD_EVENTS), '| walkovers written as a score:', len(WALKOVER_EX), '| scores raised to the race:', len(FIXED_EX), '| short, kept as recorded:', len(SHORT_EX))
json.dump({'events': ODD_EVENTS, 'walkovers': WALKOVER_EX, 'fixed': FIXED_EX, 'short': SHORT_EX}, open('walkover_check.json', 'w', encoding='utf-8'), default=str)
print('dropped odd long matches', sum(odd_long.values()), 'in', len(odd_long), 'events')
print('raw valid', len(raw_valid), 'final matches', len(matches), 'players', len(used))
print('shown (Estonian) players', sum(1 for k in used if k in SHOWN), 'background players', sum(1 for k in used if k not in SHOWN))
print('merged profiles', sum(1 for k in canon if canon[k] != k))
print('games', collections.Counter(T[m['tid']]['game'] for m in matches))
print('league list names found', len(LG_FOUND), 'of', sum(len(LG.get(c, [])) for c in ('ML', 'EL', 'TL')))
json.dump(NAME_REVIEW, open('name_review.json', 'w', encoding='utf-8'), ensure_ascii=False)   # read by report.py
# duplicate pairs for the admin panel (export_admin.py): every caught or forced pair and the pairs still to review
def _pair(t1, t2):
    a, b = by_t.get(t1, set()), by_t.get(t2, set())
    flat = lambda x: [[int(x[0][0]), x[0][1], int(x[1][0]), x[1][1]] for x in sorted(x)]
    return dict(a=t1, b=t2, na=len(a), nb=len(b), same=len(a & b), only_a=flat(a - b), only_b=flat(b - a),
                days=abs((T[t1]['date'] - T[t2]['date']).days) if t1 in T and t2 in T else None)
_pairs = {}
for t2, t1 in DUPLICATE_ENTRIES.items(): _pairs[frozenset((t1, t2))] = dict(_pair(t1, t2), kept=t1, copy=t2, forced=t2 in FORCED)
for r in OV.get('dup_review', []):
    x, y = int(r['ids'][0]), int(r['ids'][1])
    k = frozenset((x, y))
    if k not in _pairs: _pairs[k] = dict(_pair(x, y), kept=None, copy=None, forced=False)
    _pairs[k]['review'] = r['note']
json.dump(list(_pairs.values()), open('admin_dups.json', 'w', encoding='utf-8'), ensure_ascii=False)
