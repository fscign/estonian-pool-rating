"""Re-read the Estonian Billiard Association league list (Meistriliiga / Esiliiga / Teine liiga) into leagues.json.

https://eestipiljard.ee/eesti-piljardi-liigade-liigitamine/ : a table with the columns ML, EL, TL; anyone not listed plays
Rahvaliiga. The federation changes the list before or after stages (Aleksandrs 22 Nov 2026), so the daily update reads it.

Safe by design: the raw page is kept in data/leagues_page.html; if the new list looks wrong (a league empty, far fewer names,
or most names moved), the old leagues.json stays and the reason is printed (it goes into the run summary)."""
import json, re, sys, datetime, html as H
import requests
from bs4 import BeautifulSoup

URL = 'https://eestipiljard.ee/eesti-piljardi-liigade-liigitamine/'
CODES = {'ML': 'ML', 'MEISTRILIIGA': 'ML', 'EL': 'EL', 'ESILIIGA': 'EL', 'TL': 'TL', 'TEINE LIIGA': 'TL', 'TEINELIIGA': 'TL'}
NAME = re.compile(r"^[^\W\d_][\w'’.\- ]*[^\W\d_]\.?$", re.U)

def tier_of(text):
    t = re.sub(r'[\s()]+', ' ', text).strip().upper()
    return CODES.get(t) or CODES.get(t.replace(' ', ''))

def parse(page):
    """The page's table rows are name, league, name, league (seen 22 Nov 2026): each name is followed by its code.
    If no such pairs are found, fall back to columns headed by a league code (parse_columns)."""
    soup = BeautifulSoup(page, 'lxml')
    out = {'ML': [], 'EL': [], 'TL': []}
    for tr in soup.find_all('tr'):
        cells = [' '.join(c.get_text(' ', strip=True).split()) for c in tr.find_all(['td', 'th'])]
        for i in range(len(cells) - 1):
            tier = tier_of(cells[i + 1])
            if tier and NAME.match(cells[i]) and len(cells[i].split()) >= 2 and not tier_of(cells[i]):
                if cells[i] not in out[tier]: out[tier].append(cells[i])
    return out if any(out.values()) else parse_columns(page)

def parse_columns(page):
    """Column-aware: every table cell is assigned to the league named last in its column (headers may repeat further down,
    and leagues may sit side by side). Cells that are not names (numbers, empty) are skipped."""
    soup = BeautifulSoup(page, 'lxml')
    out = {'ML': [], 'EL': [], 'TL': []}
    for table in soup.find_all('table'):
        col_tier = {}
        for tr in table.find_all('tr'):
            col = 0
            for cell in tr.find_all(['td', 'th']):
                span = int(cell.get('colspan') or 1)
                text = ' '.join(cell.get_text(' ', strip=True).split())
                tier = tier_of(text)
                if tier:
                    for c in range(col, col + span): col_tier[c] = tier
                elif text and NAME.match(text) and len(text.split()) >= 2 and col in col_tier:
                    if text not in out[col_tier[col]]: out[col_tier[col]].append(text)
                col += span
    return out

def main():
    old = json.load(open('leagues.json', encoding='utf-8'))
    try:
        r = requests.get(URL, timeout=60, headers={'User-Agent': 'Mozilla/5.0 (Estonian pool rating; league list)'})
        r.raise_for_status()
    except Exception as e:
        print(f'League list: page not read ({type(e).__name__}); kept the list of {old.get("read")}'); return
    import os; os.makedirs('data', exist_ok=True)
    open('data/leagues_page.html', 'w', encoding='utf-8').write(r.text)
    new = parse(r.text)
    n_old = sum(len(old.get(k, [])) for k in ('ML', 'EL', 'TL')); n_new = sum(len(v) for v in new.values())
    old_tier = {n: k for k in ('ML', 'EL', 'TL') for n in old.get(k, [])}
    moved = sum(1 for k, v in new.items() for n in v if n in old_tier and old_tier[n] != k)
    kept = sum(1 for k, v in new.items() for n in v if old_tier.get(n) == k)
    problem = None
    if any(not v for v in new.values()): problem = 'a league came out empty'
    elif n_new < 0.7 * n_old: problem = f'only {n_new} names (was {n_old})'
    elif moved > max(15, 0.25 * n_new): problem = f'{moved} names in another league than before'
    if problem:
        print(f'League list NOT updated: {problem}. Kept the list of {old.get("read")}. The page is saved in data/leagues_page.html for a check.')
        return
    changes = []
    for k in ('ML', 'EL', 'TL'):
        add = [n for n in new[k] if old_tier.get(n) != k]; gone = [n for n in old.get(k, []) if n not in new[k]]
        if add: changes.append(f'{k} +' + ', '.join(add))
        if gone: changes.append(f'{k} -' + ', '.join(gone))
    if not changes:
        print(f'League list unchanged ({len(new["ML"])} ML, {len(new["EL"])} EL, {len(new["TL"])} TL)'); return
    json.dump(dict(source=URL, read=datetime.date.today().isoformat(), note=old.get('note', 'Anyone not listed is Rahvaliiga (RL).'), **new),
              open('leagues.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'League list updated ({len(new["ML"])} ML, {len(new["EL"])} EL, {len(new["TL"])} TL; {kept} unchanged): ' + '; '.join(changes))

if __name__ == '__main__':
    main()
