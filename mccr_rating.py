#!/usr/bin/env python3
"""MCCR starter rating builder: CCRL-inspired display, transparent score-logistic estimator."""
import argparse, csv, os, sys
from datetime import datetime, timezone
from pathlib import Path
try:
    import chess.pgn
except ImportError:
    raise SystemExit("Install dependency: pip install python-chess")

ROOT = Path(__file__).resolve().parent
RATINGS = ROOT / "ratings"
BASE = RATINGS / "base_ratings.csv"
OUT_CSV = RATINGS / "mccr_ratings.csv"
OUT_HTML = ROOT / "index.html"

def games_from(paths):
    games = []
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as f:
            while True:
                g = chess.pgn.read_game(f)
                if g is None:
                    break
                h = g.headers
                w, b, result = h.get("White", "").strip(), h.get("Black", "").strip(), h.get("Result", "")
                if not w or not b or w == b or result not in ("1-0", "0-1", "1/2-1/2"):
                    continue
                wv, bv = h.get("WhiteVersion", "").strip(), h.get("BlackVersion", "").strip()
                if wv and wv not in w: w = f"{w} {wv}"
                if bv and bv not in b: b = f"{b} {bv}"
                score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[result]
                games.append((w, b, score))
    return games

def read_base():
    result = {}
    if BASE.exists():
        with BASE.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get("engine") or row.get("name") or "").strip()
                val = (row.get("rating") or row.get("elo") or "").strip()
                if name and val:
                    try: result[name] = float(val)
                    except ValueError: pass
    return result

def expected(diff):
    x = max(-12.0, min(12.0, diff / 400.0))
    return 1.0 / (1.0 + 10.0 ** (-x))

def fit_pool(games, anchor_name="Stockfish", anchor_elo=3000.0):
    names = sorted({n for w,b,_ in games for n in (w,b)})
    if len(names) < 2: raise RuntimeError("Initial pool needs games between at least two engines.")
    ratings = {n: 0.0 for n in names}
    # Score-logistic fit; draws count as half-points. This is not BayesElo.
    for iteration in range(15000):
        grad = {n: 0.0 for n in names}
        count = {n: 0 for n in names}
        for w,b,sw in games:
            p = expected(ratings[w] - ratings[b])
            d = sw - p
            grad[w] += d; grad[b] -= d
            count[w] += 1; count[b] += 1
        rate = 8.0 / (1.0 + iteration / 800.0)
        max_step = 0.0
        for n in names:
            if count[n]:
                step = rate * grad[n] / count[n]
                ratings[n] += step
                max_step = max(max_step, abs(step))
        mean = sum(ratings.values()) / len(ratings)
        ratings = {n:r-mean for n,r in ratings.items()}
        if max_step < 1e-7: break
    anchor = anchor_name if anchor_name in ratings else max(ratings, key=ratings.get)
    offset = anchor_elo - ratings[anchor]
    return {n:r+offset for n,r in ratings.items()}, anchor

def entrant_rating(games, entrant, base):
    relevant = []
    for w,b,sw in games:
        if w == entrant: relevant.append((base.get(b), sw, b))
        elif b == entrant: relevant.append((base.get(w), 1.0-sw, w))
    if not relevant: raise RuntimeError(f"No completed games found for entrant {entrant!r}.")
    missing = sorted({name for opp,score,name in relevant if opp is None})
    if missing: raise RuntimeError("Missing frozen ratings for opponents: " + ", ".join(missing))
    score = sum(s for _,s,_ in relevant)
    lo, hi = 1000.0, 5000.0
    for _ in range(100):
        mid = (lo+hi)/2
        exp_score = sum(expected(mid-r) for r,_,_ in relevant)
        if exp_score < score: lo = mid
        else: hi = mid
    return (lo+hi)/2, len(relevant), score, sorted({name for _,_,name in relevant})

def esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def output(rows, note):
    rows.sort(key=lambda r:(-float(r["rating"]), r["engine"].casefold()))
    RATINGS.mkdir(exist_ok=True)
    fields = ["rank","engine","rating","games","score","opponents","status"]
    with OUT_CSV.open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=fields); wr.writeheader()
        for i,r in enumerate(rows,1):
            wr.writerow({"rank":i,"engine":r["engine"],"rating":f'{float(r["rating"]):.1f}',
                         "games":r.get("games",0),"score":r.get("score","—"),
                         "opponents":r.get("opponents","—"),"status":r.get("status","provisional")})
    tr=[]
    for i,r in enumerate(rows,1):
        tr.append("<tr>" + f"<td>{i}</td><td>{esc(r['engine'])}</td><td class='num'>{float(r['rating']):.1f}</td>" +
                  f"<td class='num'>{r.get('games',0)}</td><td class='num'>{esc(r.get('score','—'))}</td>" +
                  f"<td>{esc(r.get('opponents','—'))}</td><td>{esc(r.get('status','provisional'))}</td></tr>")
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page=f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCCR Rating List</title><style>
body{{font:15px system-ui,Arial;margin:1rem;line-height:1.45}}h1{{margin-bottom:.2rem}}.sub{{color:gray}}
.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:720px}}th{{background:#7899e8;color:white;text-align:left}}
td,th{{padding:.48rem .55rem;border:1px solid #aaa}}tbody tr:nth-child(even){{background:rgba(120,153,232,.16)}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.note{{padding:.7rem;border:1px solid #888;border-radius:.5rem;margin:1rem 0}}
</style></head><body><h1>MCCR Rating List</h1><div class="sub">Mobile Computer Chess Rating · Generated {stamp}</div>
<div class="note"><b>Method:</b> {esc(note)}<br><b>Scope:</b> Android engine builds tested under MCCR conditions; not directly comparable to CCRL ratings.</div>
<div class="wrap"><table><thead><tr><th>Rank</th><th>Engine</th><th>Rating</th><th>Games</th><th>Score</th><th>Opponents</th><th>Status</th></tr></thead>
<tbody>{''.join(tr)}</tbody></table></div><p class="sub">Ratings are estimates; small rating differences may not be meaningful.</p></body></html>"""
    OUT_HTML.write_text(page,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=("initial","entrant"),default=os.getenv("MCCR_MODE","initial"))
    ap.add_argument("--engine",default=os.getenv("MCCR_ENGINE",""))
    args=ap.parse_args()
    paths=sorted(Path("pgn").rglob("*.pgn"))
    if not paths: raise SystemExit("No PGN files found under pgn/. Upload PGN files first.")
    games=games_from(paths)
    if not games: raise SystemExit("No completed valid games found in PGNs.")
    if args.mode=="initial":
        ratings,anchor=fit_pool(games,os.getenv("MCCR_ANCHOR_ENGINE","Stockfish"),float(os.getenv("MCCR_ANCHOR_ELO","3000")))
        rows=[]
        for name,rating in ratings.items():
            own=[(w,b,s) for w,b,s in games if w==name or b==name]
            score=sum(s if w==name else 1-s for w,b,s in own)
            opps={b if w==name else w for w,b,s in own}
            rows.append({"engine":name,"rating":rating,"games":len(own),"score":f"{score:g}/{len(own)}",
                         "opponents":len(opps),"status":"initial / provisional"})
        note=f"Connected-pool logistic score estimate; {anchor} anchored at {float(os.getenv('MCCR_ANCHOR_ELO','3000')):.0f}. Not BayesElo."
    else:
        if not args.engine: raise SystemExit("--engine is required for entrant mode.")
        base=read_base()
        if not base: raise SystemExit("entrant mode requires ratings/base_ratings.csv with established engine ratings.")
        rating,ng,score,opps=entrant_rating(games,args.engine,base)
        rows=[{"engine":n,"rating":r,"games":0,"score":"—","opponents":"—","status":"established (frozen)"} for n,r in base.items()]
        rows.append({"engine":args.engine,"rating":rating,"games":ng,"score":f"{score:g}/{ng}",
                     "opponents":len(opps),"status":"entrant / provisional; opponents frozen"})
        note=f"Entrant performance rating against frozen ratings; existing opponents are not recalculated. Not a full-pool BayesElo rating."
    output(rows,note)
    print(f"Processed {len(games)} completed games from {len(paths)} PGN file(s).")
    print("Generated index.html and ratings/mccr_ratings.csv")

if __name__=="__main__": main()
