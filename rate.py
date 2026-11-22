"""Fargo-style rack-based ratings with 2-year half-life, placed on the FargoRate scale with a set of reference ratings."""
import sqlite3, numpy as np, datetime, json, sys, collections

DB = 'ee_pool.sqlite'
HALF_LIFE_Y = 2.0
import os
PRIOR_RACKS = 3.0
CORE_PR = float(os.environ.get('PR', 0.2))   # prior used while solving everyone together (Baltic test 22 Nov 2026)
         # virtual racks won and lost vs an average newcomer
NEWCOMER = 450           # anchored-scale rating that the prior pulls towards
TODAY = datetime.date.today()
K = np.log(2) / 100      # 100 points = 2:1 rack odds

db = sqlite3.connect(DB)
pl = db.execute('SELECT id, last_name, first_name, shown, country FROM players').fetchall()
pids = [p[0] for p in pl]; idx = {p: i for i, p in enumerate(pids)}; N = len(pids)
M = db.execute('SELECT date, player_a, player_b, score_a, score_b, game FROM matches ORDER BY date').fetchall()
dates = np.array([datetime.date.fromisoformat(m[0]).toordinal() for m in M])
A = np.array([idx[m[1]] for m in M]); B = np.array([idx[m[2]] for m in M])
WA = np.array([m[3] for m in M], float); WB = np.array([m[4] for m in M], float)
# 14.1 (straight pool): points / 14 = racks, decimals kept (decided 2 Nov 2026)
S141 = np.array([m[5] == '14.1' for m in M]); WA[S141] /= 14; WB[S141] /= 14
# racks played (shown on the site, 200 = established) count rack games only, not 14.1
NR = np.where(S141, 0.0, WA + WB)

# Baltic calculation (22 Nov 2026): Latvians, Estonians and Lithuanians each have their own newcomer group; the Latvian group is
# the solver's fixed point (any fixed point would do: the level is set afterwards by the FargoRate reference players)
BALTIC = ('LAT', 'EST', 'LIT')
LV = np.array([p[4] == 'LAT' for p in pl])
SH = np.array([bool(p[3]) for p in pl])   # shown (Estonian) players
# Newcomer pull per country (22 Nov 2026): every other country has its own group average, so weak Latvian club players are not
# pulled towards the average of all foreigners (EPBF / Matchroom pros, Finns ...), which lifted the whole Latvian pool by about 60.
_n = collections.Counter(p[4] or '?' for p in pl if p[4] not in BALTIC)
_cc = {}
GRP = np.array([0 if p[4] == 'LAT' else _cc.setdefault('S-' + p[4], len(_cc) + 1) if p[4] in BALTIC else _cc.setdefault((p[4] or '?') if _n[p[4] or '?'] >= 100 else 'other', len(_cc) + 1) for p in pl])   # small countries share one group
NG = len(_cc) + 1
# Newcomer prior: a player is pulled (3 virtual racks won and lost) towards the average of his own group.
# Latvians and foreign players get separate group averages, so strong foreign BPL players do not lift the
# point that Latvian club players are pulled towards. The Latvian group average stays at 0 on the solver scale.
def solve(upto_ord, r0=None, prior_mu=0.0, iters=400, mu_f=None):
    sel = dates <= upto_ord
    a, b, wa, wb = A[sel], B[sel], WA[sel], WB[sel]
    age = (upto_ord - dates[sel]) / 365.25
    w = 0.5 ** (age / HALF_LIFE_Y)
    r = np.zeros(N) if r0 is None else r0.copy()
    active = np.zeros(N, bool); active[a] = True; active[b] = True
    mu_g = np.zeros(NG) if mu_f is None else np.array(mu_f, float).copy()
    n = wa + wb
    for _ in range(iters):
        p = 1 / (1 + np.exp(-K * (r[a] - r[b])))           # P(a wins a rack)
        ga = w * (wa - n * p); h = w * n * p * (1 - p) * K
        g = np.bincount(a, ga, N) - np.bincount(b, ga, N)
        H = np.bincount(a, h, N) + np.bincount(b, h, N)
        mu = np.where(LV, prior_mu, mu_g[GRP])
        pp = 1 / (1 + np.exp(-K * (r - mu)))
        gp = CORE_PR - 2 * CORE_PR * pp; hp = 2 * CORE_PR * pp * (1 - pp) * K
        g += gp; H += hp
        step = np.clip(g / H, -60, 60)
        step[~active] = 0
        r += step
        # the overall level is pinned only by the weak prior, so move everyone together towards it as well
        pp = 1 / (1 + np.exp(-K * (r - mu)))
        gp = CORE_PR - 2 * CORE_PR * pp; hp = 2 * CORE_PR * pp * (1 - pp) * K
        al, af = active & LV, active & ~LV
        shift = float(np.clip(gp[al].sum() / hp[al].sum(), -60, 60)) if al.any() else 0.0
        r[active] += shift
        # each foreign country's average follows its own active players
        sg = np.bincount(GRP[af], -gp[af], NG); sh = np.bincount(GRP[af], hp[af], NG)
        dmg = np.where(sh > 0, np.clip(sg / np.where(sh > 0, sh, 1), -60, 60), 0.0); dmg[0] = 0.0
        mu_g += dmg; dmf = float(np.abs(dmg).max())
        if np.abs(step).max() < 0.005 and abs(shift) < 0.005 and dmf < 0.02: break
    nr = NR[sel]
    racks = np.bincount(a, nr, N) + np.bincount(b, nr, N)   # rack games only (no 14.1)
    eff = np.bincount(a, w * n, N) + np.bincount(b, w * n, N)
    solve.mu_f = mu_g
    return r, active, racks, eff


# Newcomer pull without squeezing everyone else (Baltic test 22 Nov 2026): everyone is first solved together with only a very weak
# pull (CORE_PR), so weak occasional players are no longer lifted towards the group average, which used to narrow the whole scale
# (strong players beat weak ones more often than the ratings said). Then each player's own shown rating gets the normal pull
# (PRIOR_RACKS) with his opponents held at their solved ratings, so a newcomer's number stays steady without moving anyone else.
def refit(rc, upto_ord, prior_mu=0.0, iters=60):
    sel = dates <= upto_ord
    a, b, wa, wb = A[sel], B[sel], WA[sel], WB[sel]
    w = 0.5 ** (((upto_ord - dates[sel]) / 365.25) / HALF_LIFE_Y); n = wa + wb
    mu = np.where(LV, prior_mu, solve.mu_f[GRP])
    r = rc.copy(); ra_o, rb_o = rc[b], rc[a]
    for _ in range(iters):
        pa = 1 / (1 + np.exp(-K * (r[a] - ra_o))); pb = 1 / (1 + np.exp(-K * (r[b] - rb_o)))
        g = np.bincount(a, w * (wa - n * pa), N) + np.bincount(b, w * (wb - n * pb), N)
        H = np.bincount(a, w * n * pa * (1 - pa) * K, N) + np.bincount(b, w * n * pb * (1 - pb) * K, N)
        pp = 1 / (1 + np.exp(-K * (r - mu)))
        g += PRIOR_RACKS - 2 * PRIOR_RACKS * pp; H += 2 * PRIOR_RACKS * pp * (1 - pp) * K
        st = np.clip(g / H, -60, 60); r += st
        if np.abs(st).max() < 0.01: break
    return r

# Determine offset (unanchored -> anchored) with prior mean consistent with NEWCOMER
today = TODAY.toordinal(); offset = 0.0; r = None
# The prior only fixes where the scale sits; anchoring then shifts the whole scale, so solve once with prior at 0.
r_core, active, racks, eff = solve(today, None, prior_mu=0.0, iters=3000)
r = refit(r_core, today)
# Level (Baltic test 22 Nov 2026, Aleksandrs): every player with FargoRate robustness 1,000+ and 300+ racks here in the last 2 years,
# any country and level (fargo/reference.json); the whole scale is shifted so that their median difference to FargoRate is 0
# (fargo/reference.json: source profile id, name and FargoRate of each; found through player_profiles, so merges do not lose them)
_prof = {s_: p_ for s_, p_ in db.execute('SELECT source_id, player_id FROM player_profiles')}
QF = []
for q in json.load(open('fargo/reference.json', encoding='utf-8'))['players']:
    pid = _prof.get(str(q['id']), q['id'])
    if pid in idx and active[idx[pid]]: QF.append((idx[pid], q['fargo']))
offset = float(np.median([f - r[i] for i, f in QF]))
print('reference players', len(QF))
print('newcomer pull point on the anchored scale:', round(offset))
final = r + offset
print('offset', round(offset, 1), 'newcomer points by country', {k: round(solve.mu_f[v] + offset) for k, v in _cc.items() if k in ('S-EST', 'S-LIT', 'FIN', 'SWE', 'NOR', 'DEN', 'GER', 'POL')})
print('reference check (FargoRate, ours):', [(pl[i][1], f, round(final[i])) for i, f in QF if f >= 700])

# current ratings table
nmatch = np.bincount(A, None, N) + np.bincount(B, None, N)
lastp = {}
for m in M: lastp[m[1]] = m[0]; lastp[m[2]] = m[0]
order = sorted([i for i in range(N) if active[i]], key=lambda i: (not pl[i][3], -final[i]))
db.execute('DELETE FROM ratings'); db.execute('DELETE FROM rating_history')
rank = 0
for i in order:
    rank += 1 if pl[i][3] else 0
    db.execute('INSERT INTO ratings VALUES(?,?,?,?,?,?,?)', (pids[i], round(float(final[i]), 1), int(racks[i]), round(float(eff[i]), 1),
               int(nmatch[i]), lastp[pids[i]], rank if pl[i][3] else None))

# monthly history (month-end reconstructions)
# The scale is pinned to the average Latvian player, and many new (mostly weaker) players joined over the years,
# so without a correction everyone drifts upwards over time (even players who stopped playing).
# Each month is therefore shifted so that players who have not played since that month keep, on average (median),
# the rating they have today: a player's history only moves because of his own results and his opponents'.
last_ord = np.full(N, -1); nm_cnt = np.zeros(N, int)
for k in range(len(M)):
    last_ord[A[k]] = max(last_ord[A[k]], dates[k]); last_ord[B[k]] = max(last_ord[B[k]], dates[k])
snap = []
# a player's history starts once he has 100 racks within 2 years; before that the rating is mostly the newcomer starting level
MIN_RACKS = 100
started = np.zeros(N, bool)
y, mth = 2011, 12; rr = None; rc = None; mf = None
while (y, mth) <= (TODAY.year, TODAY.month):
    nm = datetime.date(y + (mth == 12), mth % 12 + 1, 1)
    end = min(nm - datetime.timedelta(days=1), TODAY)
    rc, act, _, _ = solve(end.toordinal(), rc, prior_mu=0.0, iters=3000, mu_f=mf)
    rr = refit(rc, end.toordinal())
    mf = solve.mu_f
    sel = dates <= end.toordinal(); recent = sel & (dates > end.toordinal() - 730)
    rec = np.zeros(N, bool); rec[A[recent]] = True; rec[B[recent]] = True
    nr = NR[recent]   # history starts after 100 racks of rack games
    started |= (np.bincount(A[recent], nr, N) + np.bincount(B[recent], nr, N)) >= MIN_RACKS
    rec &= started
    cnt = np.bincount(A[sel], None, N) + np.bincount(B[sel], None, N)
    ref = SH & (last_ord <= end.toordinal()) & (cnt >= 20) & (last_ord >= 0)
    corr = float(np.median(r[ref] - rr[ref])) if ref.sum() >= 15 else None
    snap.append((f'{y}-{mth:02d}', rr.copy(), rec, corr, int(ref.sum())))
    y, mth = (y + 1, 1) if mth == 12 else (y, mth + 1)
# months with too few reference players take the correction of the nearest month that has one
known = [k for k, s_ in enumerate(snap) if s_[3] is not None]
# remove one-month jumps in the correction (compare with the centred 7-month median): with few reference players one month can jump by 10 points,
# which would show as a fake spike in everybody's history
_raw = {k: snap[k][3] for k in known}
for k in known:
    win = [_raw[q] for q in known if abs(q - k) <= 3]
    med = float(np.median(win))
    if abs(_raw[k] - med) > 3: snap[k] = snap[k][:3] + (med,) + snap[k][4:]   # only one-month outliers are replaced
rows = 0
for k, (mon, rrm, rec, corr, nref) in enumerate(snap):
    if corr is None: corr = snap[min(known, key=lambda q: abs(q - k))][3] if known else 0.0
    for i in np.where(rec)[0]:
        db.execute('INSERT INTO rating_history VALUES(?,?,?)', (pids[i], mon, round(float(rrm[i] + corr + offset))))
        rows += 1
    if mon.endswith('-12') or k == len(snap) - 1: print('history', mon, 'drift correction', round(corr, 1), 'reference players', nref)
db.commit()
print('history rows', rows)
for row in db.execute('SELECT r.rank, p.first_name||" "||p.last_name, r.rating, r.racks, r.last_played FROM ratings r JOIN players p ON p.id=r.player_id WHERE r.last_played>=date("now","-1 year") AND r.racks>=150 ORDER BY r.rating DESC LIMIT 30'):
    print(row)
