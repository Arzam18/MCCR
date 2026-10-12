#!/usr/bin/env python3
"""MCCR cumulative BayesElo publisher with persistent, deduplicated game storage."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, subprocess, tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import chess.pgn
from chess.pgn import StringExporter

ROOT = Path(__file__).resolve().parent
PGN_DIR = ROOT / 'pgn'
RATINGS_DIR = ROOT / 'ratings'
BASE_CSV = RATINGS_DIR / 'base_ratings.csv'
OUT_CSV = RATINGS_DIR / 'mccr_ratings.csv'
OUT_HTML = ROOT / 'index.html'
DB_FILE = RATINGS_DIR / 'games.jsonl'
ALIASES_FILE = RATINGS_DIR / 'engine_aliases.json'
CONFIG_FILE = RATINGS_DIR / 'mccr_config.json'
BAYESELO = Path(os.getenv('BAYESELO_BIN', '/usr/local/bin/bayeselo'))
INITIAL_PGN = PGN_DIR / 'initial.pgn'
VALID_RESULTS = {'1-0', '0-1', '1/2-1/2'}


def load_json(path, default):
    if not path.exists(): return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_base():
    result = {}
    if BASE_CSV.exists():
        with BASE_CSV.open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                key = (row.get('engine_id') or row.get('engine') or '').strip()
                if key:
                    try:
                        result[key] = {'rating': float(row['rating']), 'plus': int(float(row.get('plus') or 0)), 'minus': int(float(row.get('minus') or 0)), 'engine': (row.get('engine') or key).strip()}
                    except (ValueError, KeyError): pass
    return result


def write_base(base):
    RATINGS_DIR.mkdir(parents=True, exist_ok=True)
    with BASE_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['engine_id', 'engine', 'rating', 'plus', 'minus'])
        for eid, r in sorted(base.items(), key=lambda x: (-x[1]['rating'], x[1]['engine'].casefold())):
            w.writerow([eid, r['engine'], f"{r['rating']:.1f}", r.get('plus', 0), r.get('minus', 0)])


def valid_game(game):
    h = game.headers
    return bool(h.get('White','').strip() and h.get('Black','').strip() and h['White'].strip() != h['Black'].strip() and h.get('Result') in VALID_RESULTS)


def game_fingerprint(game):
    h = game.headers
    moves = ' '.join(m.uci() for m in game.mainline_moves())
    identity = '\x1f'.join([h.get('White','').strip(), h.get('Black','').strip(), h.get('Result',''), h.get('Date',''), h.get('Round',''), h.get('Event',''), moves])
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def load_db():
    games, seen = [], set()
    if DB_FILE.exists():
        with DB_FILE.open(encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                item = json.loads(line)
                fp = item.get('fingerprint')
                if fp and fp not in seen:
                    games.append(item); seen.add(fp)
    return games, seen


def read_pgn_files(paths):
    for path in paths:
        with path.open('r', encoding='utf-8', errors='replace') as f:
            while True:
                g = chess.pgn.read_game(f)
                if g is None: break
                if valid_game(g): yield path, g


def parse_bayeselo_ratings(text):
    parsed = {}
    # BayesElo's ratings table: rank name Elo + - games score% opponent draws%.
    pat = re.compile(r'^\s*(\d+)\s+(.+?)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+(-?\d+)\s+([\d.]+)%\s*$')
    for line in text.splitlines():
        m = pat.match(line)
        if m:
            _, name, elo, plus, minus, ngames, score, opp, draws = m.groups()
            parsed[name.strip()] = {'rating': float(elo), 'plus': int(plus), 'minus': int(minus), 'bayes_games': int(ngames), 'opponent_rating': float(opp)}
    if not parsed:
        raise RuntimeError('Could not parse BayesElo ratings table. BayesElo output follows:\n' + text[-6000:])
    return parsed


def run_bayeselo(games, anchor_id, anchor_rating=3200):
    if not BAYESELO.is_file(): raise RuntimeError(f'BayesElo executable not found: {BAYESELO}')
    # Build a temporary PGN from the persistent database. IDs, not changing display labels,
    # are the stable player identities, so engine version updates combine old and new games.
    with tempfile.TemporaryDirectory(prefix='mccr-') as td:
        pgn_path = Path(td) / 'cumulative.pgn'
        with pgn_path.open('w', encoding='utf-8') as out:
            for i, item in enumerate(games, 1):
                g = chess.pgn.Game()
                g.headers['Event'] = f'MCCR cumulative game {i}'
                g.headers['Site'] = 'MCCR'
                g.headers['Date'] = item.get('date') or '????.??.??'
                g.headers['Round'] = str(i)
                g.headers['White'] = item['white_id']; g.headers['Black'] = item['black_id']; g.headers['Result'] = item['result']
                board = g.board()
                node = g
                for uci in item.get('moves_uci', []):
                    try: move = board.parse_uci(uci)
                    except ValueError: break
                    node = node.add_variation(move)
                    board.push(move)
                out.write(g.accept(StringExporter(headers=True, variations=False, comments=False)) + '\n\n')
        cmds = [f'readpgn {pgn_path}', 'elo', 'mm 0 1', 'exactdist', f'offset {int(round(anchor_rating))} {anchor_id}', 'ratings', 'x', '']
        proc = subprocess.run([str(BAYESELO)], input='\n'.join(cmds), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT, timeout=240)
        if proc.returncode != 0: raise RuntimeError(f'BayesElo failed ({proc.returncode}):\n{proc.stdout[-6000:]}')
        return parse_bayeselo_ratings(proc.stdout)


def stats_for(games):
    s = defaultdict(lambda: {'games':0,'wins':0,'draws':0,'losses':0,'score':0.0,'opponents':set()})
    for g in games:
        w,b,r = g['white_id'],g['black_id'],g['result']
        s[w]['games'] += 1; s[b]['games'] += 1; s[w]['opponents'].add(b); s[b]['opponents'].add(w)
        if r == '1-0': s[w]['wins'] += 1; s[w]['score'] += 1; s[b]['losses'] += 1
        elif r == '0-1': s[b]['wins'] += 1; s[b]['score'] += 1; s[w]['losses'] += 1
        else: s[w]['draws'] += 1; s[b]['draws'] += 1; s[w]['score'] += .5; s[b]['score'] += .5
    return s


def esc(x):
    return str(x).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;').replace("'",'&#39;')


def write_outputs(rows, note):
    rows.sort(key=lambda r: (-r['rating'], r['engine'].casefold()))
    fields = ['rank','engine','rating','plus','minus','score_pct','opponent_rating','draw_pct','games','wins','draws','losses','opponents','status']
    with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for rank, row in enumerate(rows, 1): w.writerow({'rank':rank, **{k:row.get(k,'') for k in fields if k != 'rank'}})
    body = []
    for rank, r in enumerate(rows,1):
        body.append('<tr>' + f"<td>{rank}</td><td>{esc(r['engine'])}</td><td>{r['rating']:.0f}</td><td>+{r['plus']}</td><td>−{r['minus']}</td><td>{r['score_pct']:.1f}%</td><td>{r['opponent_rating']}</td><td>{r['draw_pct']:.1f}%</td><td>{r['games']}</td><td>{r['wins']}</td><td>{r['draws']}</td><td>{r['losses']}</td><td>{r['opponents']}</td><td>{esc(r['status'])}</td></tr>")
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    OUT_HTML.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MCCR Rating List</title><style>body{{font:14px system-ui,Arial;margin:1rem;color:#20252b;background:#e5f3ed;line-height:1.45}}h1{{text-align:center;color:#267747}}.sub{{text-align:center;color:#65736d}}.note{{padding:.7rem;border:1px solid #9bb9aa;border-radius:.4rem;margin:1rem 0;background:#f5fbf7}}.wrap{{overflow-x:auto;background:white}}table{{border-collapse:collapse;width:100%;min-width:1120px;font-size:13px}}th{{background:#7899e8;color:white;white-space:nowrap}}td,th{{padding:.42rem .5rem;border:1px solid #bdc9c4;text-align:right;white-space:nowrap}}td:nth-child(2),th:nth-child(2){{text-align:left}}tbody tr:nth-child(even){{background:#edf2fa}}</style></head><body><h1>MCCR Rating List</h1><div class="sub">Mobile Computer Chess Rating · Generated {stamp}</div><div class="note"><b>Method:</b> {esc(note)}<br><b>Anchor:</b> initial Stockfish reference = 3200 MCCR Elo. Not directly comparable to CCRL.<br><b>History:</b> ratings and W/D/L use all unique games retained in ratings/games.jsonl, even after source PGNs are deleted.</div><div class="wrap"><table><thead><tr><th>Rank</th><th>Engine</th><th>Rating</th><th>+</th><th>−</th><th>Score</th><th>Avg. Opponent</th><th>Draws</th><th>Games</th><th>W</th><th>D</th><th>L</th><th>Opponents</th><th>Status</th></tr></thead><tbody>{''.join(body)}</tbody></table></div></body></html>''', encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--action', choices=['initial','add','update'], default=os.getenv('MCCR_ACTION','initial'))
    p.add_argument('--engine', default=os.getenv('MCCR_ENGINE',''), help='Exact engine player name in the uploaded PGN')
    p.add_argument('--display-name', default=os.getenv('MCCR_DISPLAY_NAME',''))
    p.add_argument('--replace-existing', default=os.getenv('MCCR_REPLACE_EXISTING',''), help='Existing display name to replace on update')
    args = p.parse_args()
    aliases = load_json(ALIASES_FILE, {})
    config = load_json(CONFIG_FILE, {})
    entities = config.setdefault('engines', {})
    db, seen = load_db()
    base = read_base()

    paths = sorted(PGN_DIR.rglob('*.pgn'))
    if args.action == 'initial':
        if not INITIAL_PGN.exists(): raise SystemExit('Initial action requires pgn/initial.pgn.')
        # A deliberate initial run is allowed only before a database has been established.
        if db and config.get('initialized'):
            raise SystemExit('MCCR is already initialized. Use Add engine or Update existing engine; do not rerun initial and overwrite history.')
        # Migration path: if the previous version already published a base CSV but had no
        # permanent database, import every PGN still present so its history is not omitted.
        legacy_base = BASE_CSV.exists() and BASE_CSV.stat().st_size > 20 and not db
        initial_import_paths = paths if legacy_base else [INITIAL_PGN]
        pending = list(read_pgn_files(initial_import_paths))
        raw_names = {n for _,g in pending for n in (g.headers['White'].strip(), g.headers['Black'].strip())}
        stockfish = sorted((n for n in raw_names if n.casefold().startswith('stockfish')), key=str.casefold)
        if not stockfish: raise SystemExit('No Stockfish player found in initial.pgn to anchor at 3200.')
        for name in raw_names:
            aliases[name] = name; entities.setdefault(name, {'display_name':name})
        config['anchor_id'] = aliases[stockfish[0]]; config['initialized'] = True
    else:
        if not config.get('initialized') or not db: raise SystemExit('Run Initial first to establish MCCR history and the Stockfish anchor.')
        if not args.engine.strip(): raise SystemExit('Enter the exact PGN player name of the engine being added/updated.')
        if not args.display_name.strip(): raise SystemExit('Enter the display name to show in the MCCR rating list.')
        # Determine an identity to attach the PGN's raw player name to.
        if args.action == 'add':
            if args.engine in aliases: raise SystemExit(f'{args.engine!r} is already mapped to an MCCR engine. Use Update existing engine instead.')
            eid = args.engine.strip()
            if eid in entities: raise SystemExit('That engine identity already exists; choose Update existing engine if this is a new version.')
            entities[eid] = {'display_name':args.display_name.strip()}
        else:
            if not args.replace_existing.strip(): raise SystemExit('For Update, select the existing engine display name to replace.')
            matches = [eid for eid, ent in entities.items() if ent.get('display_name','').casefold() == args.replace_existing.strip().casefold()]
            if len(matches) != 1: raise SystemExit(f'Could not uniquely find existing engine {args.replace_existing!r}. Existing names: ' + ', '.join(sorted(ent.get('display_name',eid) for eid,ent in entities.items())))
            eid = matches[0]
            entities[eid]['display_name'] = args.display_name.strip()
        aliases[args.engine.strip()] = eid

    # Import games from the initial file once, or all currently present PGNs for add/update.
    import_paths = initial_import_paths if args.action == 'initial' else [x for x in paths if x.exists()]
    added = 0
    for path, g in read_pgn_files(import_paths):
        fp = game_fingerprint(g)
        if fp in seen: continue
        wraw, braw = g.headers['White'].strip(), g.headers['Black'].strip()
        if wraw not in aliases or braw not in aliases:
            unknown = [n for n in (wraw,braw) if n not in aliases]
            raise SystemExit('PGN includes unregistered engine name(s): ' + ', '.join(unknown) + '. Register one engine per run using the exact PGN name.')
        item = {'fingerprint':fp, 'white_id':aliases[wraw], 'black_id':aliases[braw], 'white_raw':wraw, 'black_raw':braw,
                'result':g.headers['Result'], 'date':g.headers.get('Date',''), 'moves_uci':[m.uci() for m in g.mainline_moves()], 'source':path.name}
        db.append(item); seen.add(fp); added += 1
    if not db: raise SystemExit('No valid games were imported.')
    # Ensure every historical game remains attached to an engine identity.
    ids = {x for g in db for x in (g['white_id'],g['black_id'])}
    for eid in ids: entities.setdefault(eid, {'display_name':eid})
    bayes = run_bayeselo(db, config['anchor_id'], 3200.0)
    missing = ids - set(bayes)
    if missing: raise RuntimeError('BayesElo did not return ratings for identities: ' + ', '.join(sorted(missing)))

    # Initial run publishes every calculated estimate. Later runs freeze everyone except the
    # selected add/update identity, whose rating uses all its historical and newly imported games.
    if args.action == 'initial':
        for eid in ids: base[eid] = {'rating':bayes[eid]['rating'], 'plus':bayes[eid]['plus'], 'minus':bayes[eid]['minus'], 'engine':entities[eid]['display_name']}
        updated_id = None
    else:
        updated_id = aliases[args.engine.strip()]
        if args.action == 'add' and updated_id in base: raise SystemExit('This engine is already in the published base; use Update instead.')
        base[updated_id] = {'rating':bayes[updated_id]['rating'], 'plus':bayes[updated_id]['plus'], 'minus':bayes[updated_id]['minus'], 'engine':entities[updated_id]['display_name']}
        # Refresh display names without changing frozen ratings for other engines.
        for eid in list(base):
            if eid in entities: base[eid]['engine'] = entities[eid]['display_name']

    stats = stats_for(db)
    rows = []
    for eid, st in stats.items():
        rating_rec = base.get(eid) or {'rating':bayes[eid]['rating'],'plus':bayes[eid]['plus'],'minus':bayes[eid]['minus'],'engine':entities[eid]['display_name']}
        total = st['games']; opps = st['opponents']
        opp_ratings = [base[o]['rating'] for o in opps if o in base]
        rows.append({'engine':entities.get(eid,{}).get('display_name',rating_rec['engine']), 'rating':rating_rec['rating'], 'plus':rating_rec.get('plus',0), 'minus':rating_rec.get('minus',0),
            'score_pct':100*st['score']/total if total else 0, 'opponent_rating':round(sum(opp_ratings)/len(opp_ratings)) if opp_ratings else '—',
            'draw_pct':100*st['draws']/total if total else 0, 'games':total, 'wins':st['wins'], 'draws':st['draws'], 'losses':st['losses'], 'opponents':len(opps),
            'status':'initial / provisional' if args.action == 'initial' else ('updated version' if eid == updated_id and args.action == 'update' else ('new entrant / provisional' if eid == updated_id else 'established / frozen'))})
    # Persist database first-class; source PGNs can now be removed after successful run.
    RATINGS_DIR.mkdir(parents=True, exist_ok=True)
    with DB_FILE.open('w', encoding='utf-8') as f:
        for item in db: f.write(json.dumps(item, ensure_ascii=False, separators=(',',':'))+'\n')
    save_json(ALIASES_FILE, aliases); save_json(CONFIG_FILE, config); write_base(base)
    note = f"BayesElo on {len(db)} unique cumulative games. {added} new games imported this run. Historical games remain in ratings/games.jsonl; duplicate games are skipped. Existing ratings are frozen except the engine explicitly added or updated."
    if args.action == 'initial' and legacy_base:
        note += ' Legacy migration: all PGNs still present in pgn/ were imported because the previous version had no permanent game database.'
    write_outputs(rows, note)
    print(f'Imported {added} new unique games; {len(db)} total games retained in {DB_FILE.relative_to(ROOT)}.')
    print(f'Generated {OUT_CSV.relative_to(ROOT)} and {OUT_HTML.relative_to(ROOT)}.')

if __name__ == '__main__':
    try: main()
    except (RuntimeError, subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc: raise SystemExit(f'MCCR update failed: {exc}')
