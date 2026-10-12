#!/usr/bin/env python3
"""MCCR rating publisher using the official BayesElo command-line calculator."""
from __future__ import annotations
import argparse
import csv
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import chess.pgn
except ImportError as exc:
    raise SystemExit("Missing dependency: install python-chess") from exc

ROOT = Path(__file__).resolve().parent
PGN_DIR = ROOT / "pgn"
RATINGS_DIR = ROOT / "ratings"
BASE_CSV = RATINGS_DIR / "base_ratings.csv"
OUT_CSV = RATINGS_DIR / "mccr_ratings.csv"
OUT_HTML = ROOT / "index.html"
BAYESELO = Path(os.getenv("BAYESELO_BIN", "/usr/local/bin/bayeselo"))
INITIAL_PGN = PGN_DIR / "initial.pgn"


def read_games(paths: list[Path]) -> list[dict]:
    games: list[dict] = []
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break
                headers = game.headers
                white = headers.get("White", "").strip()
                black = headers.get("Black", "").strip()
                result = headers.get("Result", "").strip()
                if not white or not black or white == black or result not in {"1-0", "0-1", "1/2-1/2"}:
                    continue
                games.append({"white": white, "black": black, "result": result, "file": path.name})
    return games


def read_base() -> dict[str, float]:
    result: dict[str, float] = {}
    if BASE_CSV.exists():
        with BASE_CSV.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("engine") or row.get("name") or "").strip()
                value = (row.get("rating") or row.get("elo") or "").strip()
                if name and value:
                    try:
                        result[name] = float(value)
                    except ValueError:
                        continue
    return result


def write_base(ratings: dict[str, float]) -> None:
    RATINGS_DIR.mkdir(parents=True, exist_ok=True)
    with BASE_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["engine", "rating"])
        for name, rating in sorted(ratings.items(), key=lambda item: (-item[1], item[0].casefold())):
            writer.writerow([name, f"{rating:.1f}"])


def wdl_stats(games: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"games": 0, "wins": 0, "draws": 0, "losses": 0, "score": 0.0, "opponents": set()})
    for game in games:
        w, b, result = game["white"], game["black"], game["result"]
        stats[w]["games"] += 1
        stats[b]["games"] += 1
        stats[w]["opponents"].add(b)
        stats[b]["opponents"].add(w)
        if result == "1-0":
            stats[w]["wins"] += 1; stats[w]["score"] += 1
            stats[b]["losses"] += 1
        elif result == "0-1":
            stats[b]["wins"] += 1; stats[b]["score"] += 1
            stats[w]["losses"] += 1
        else:
            stats[w]["draws"] += 1; stats[b]["draws"] += 1
            stats[w]["score"] += 0.5; stats[b]["score"] += 0.5
    return stats


def pgn_players(paths: list[Path]) -> set[str]:
    return {name for game in read_games(paths) for name in (game["white"], game["black"])}


def choose_stockfish_name(names: set[str], preferred: str = "") -> str:
    if preferred and preferred in names:
        return preferred
    matches = sorted((name for name in names if name.casefold().startswith("stockfish")), key=str.casefold)
    if not matches:
        raise RuntimeError("Could not find a Stockfish player in the PGNs. MCCR uses Stockfish as the 3200-point anchor; check the PGN White/Black names.")
    return matches[0]


def parse_bayeselo_ratings(text: str) -> dict[str, dict]:
    """Parse BayesElo's `ratings` table while preserving engine names with spaces."""
    parsed: dict[str, dict] = {}
    # Expected columns: rank, name, Elo, +, -, games, score%, opponent, draws%.
    pattern = re.compile(r"^\s*(\d+)\s+(.+?)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+%)\s+(-?\d+)\s+([\d.]+%)\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rank, name, elo, plus, minus, games, score_pct, opponent, draws_pct = match.groups()
        parsed[name.strip()] = {"rating": float(elo), "plus": int(plus), "minus": int(minus), "bayes_games": int(games), "opponent_rating": float(opponent)}
    if not parsed:
        raise RuntimeError("Could not parse BayesElo ratings output. Output was:\n" + text[-5000:])
    return parsed


def run_bayeselo(paths: list[Path], stockfish_name: str, offset: float = 3200.0) -> dict[str, dict]:
    if not BAYESELO.is_file():
        raise RuntimeError(f"BayesElo executable not found at {BAYESELO}. The GitHub Actions workflow must build it first.")
    if not paths:
        raise RuntimeError("No PGN files selected for BayesElo.")
    # BayesElo command names may contain spaces; the engine name is the remainder of the offset command.
    commands = [f'readpgn {path.resolve()}' for path in paths]
    commands += ["elo", "mm 0 1", "exactdist", f"offset {int(round(offset))} {stockfish_name}", "ratings", "x", "x", ""]
    proc = subprocess.run([str(BAYESELO)], input="\n".join(commands), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT, timeout=180)
    # BayesElo's ratings table is normally printed to stdout; capture it from the transcript.
    parsed = parse_bayeselo_ratings(proc.stdout)
    if proc.returncode != 0:
        raise RuntimeError(f"BayesElo exited with status {proc.returncode}:\n{proc.stdout[-4000:]}")
    return parsed


def html_escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def write_outputs(rows: list[dict], method_note: str) -> None:
    rows.sort(key=lambda row: (-float(row["rating"]), row["engine"].casefold()))
    RATINGS_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["rank", "engine", "rating", "plus", "minus", "score_pct", "opponent_rating", "draw_pct", "games", "wins", "draws", "losses", "opponents", "status"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, row in enumerate(rows, 1):
            writer.writerow({"rank": rank, **{key: row.get(key, "") for key in fields if key != "rank"}})

    html_rows = []
    for rank, row in enumerate(rows, 1):
        html_rows.append(
            "<tr>"
            f"<td>{rank}</td><td>{html_escape(row['engine'])}</td>"
            f"<td class='num'>{float(row['rating']):.0f}</td>"
            f"<td class='num'>+{row.get('plus', 0)}</td><td class='num'>−{row.get('minus', 0)}</td>"
            f"<td class='num'>{row.get('score_pct', 0):.1f}%</td>"
            f"<td class='num'>{row.get('opponent_rating', '—')}</td><td class='num'>{row.get('draw_pct', 0):.1f}%</td>"
            f"<td class='num'>{row.get('games', 0)}</td><td class='num'>{row.get('wins', 0)}</td>"
            f"<td class='num'>{row.get('draws', 0)}</td><td class='num'>{row.get('losses', 0)}</td>"
            f"<td class='num'>{row.get('opponents', 0)}</td><td>{html_escape(row.get('status', 'provisional'))}</td></tr>"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCCR Rating List</title><style>
:root{{color-scheme:light}}body{{font:14px system-ui,Arial,sans-serif;margin:1rem;line-height:1.45;color:#20252b;background:#e5f3ed}}
h1{{text-align:center;color:#267747;margin:.2rem 0}}.sub{{color:#65736d;text-align:center}}.note{{padding:.7rem;border:1px solid #9bb9aa;border-radius:.4rem;margin:1rem 0;background:#f5fbf7}}
.wrap{{overflow-x:auto;background:white}}table{{border-collapse:collapse;width:100%;min-width:1120px;font-size:13px}}th{{background:#7899e8;color:white;text-align:center;white-space:nowrap}}
td,th{{padding:.42rem .5rem;border:1px solid #bdc9c4}}td:nth-child(1){{text-align:right;font-weight:600}}td:nth-child(2){{font-weight:600}}tbody tr:nth-child(even){{background:#edf2fa}}.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.footer{{margin-top:.8rem;color:#65736d;font-size:12px}}
</style></head><body><h1>MCCR Rating List</h1><div class="sub">Mobile Computer Chess Rating · Generated {stamp}</div>
<div class="note"><b>Rating method:</b> {html_escape(method_note)}<br><b>Anchor:</b> Stockfish = 3200 MCCR Elo. This is an internal Android-engine rating scale and is not directly comparable to CCRL ratings.<br><b>W/D/L:</b> wins, draws and losses from all PGNs included in the current rating update.</div>
<div class="wrap"><table><thead><tr><th>Rank</th><th>Engine</th><th>Rating</th><th>+</th><th>−</th><th>Score</th><th>Avg. Opponent</th><th>Draws</th><th>Games</th><th>W</th><th>D</th><th>L</th><th>Opponents</th><th>Status</th></tr></thead><tbody>{''.join(html_rows)}</tbody></table></div>
<p class="footer">Ratings are statistical estimates. Small differences may not be meaningful. Only completed, valid-result PGN games are counted.</p></body></html>"""
    OUT_HTML.write_text(page, encoding="utf-8")


def make_rows(games: list[dict], rating_map: dict[str, dict], fixed_ratings: dict[str, float] | None = None, entrant: str | None = None) -> list[dict]:
    stats = wdl_stats(games)
    names = set(stats)
    rows = []
    for name in names:
        if fixed_ratings is not None and name in fixed_ratings:
            rating = fixed_ratings[name]
            status = "established / frozen"
            plus = minus = 0
        else:
            if name not in rating_map:
                continue
            rating = rating_map[name]["rating"]
            plus = rating_map[name]["plus"]
            minus = rating_map[name]["minus"]
            status = "initial / provisional" if entrant is None else ("new entrant / provisional" if name == entrant else "established / frozen")
        st = stats[name]
        total = st["games"]
        score_pct = (100.0 * st["score"] / total) if total else 0.0
        draw_pct = (100.0 * st["draws"] / total) if total else 0.0
        opp_names = st["opponents"]
        if fixed_ratings is not None:
            known_opps = [fixed_ratings[o] for o in opp_names if o in fixed_ratings]
            if name in rating_map:
                known_opps += [fixed_ratings[o] for o in opp_names if o not in fixed_ratings and o in fixed_ratings]
            avg_opp = round(sum(known_opps) / len(known_opps)) if known_opps else "—"
        else:
            avg_opp = rating_map.get(name, {}).get("opponent_rating", "—")
        rows.append({"engine": name, "rating": rating, "plus": plus, "minus": minus, "score_pct": score_pct,
                     "opponent_rating": avg_opp, "draw_pct": draw_pct, "games": total,
                     "wins": st["wins"], "draws": st["draws"], "losses": st["losses"],
                     "opponents": len(opp_names), "status": status})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish MCCR ratings using BayesElo")
    parser.add_argument("--mode", choices=("initial", "entrant"), default=os.getenv("MCCR_MODE", "initial"))
    parser.add_argument("--engine", default=os.getenv("MCCR_ENGINE", ""), help="Exact PGN name of new entrant; omit to auto-detect a single unranked engine")
    args = parser.parse_args()
    if not BAYESELO.is_file():
        raise SystemExit(f"BayesElo executable not found: {BAYESELO}")

    all_paths = sorted(PGN_DIR.rglob("*.pgn"))
    if not all_paths:
        raise SystemExit("No PGN files found under pgn/. Add pgn/initial.pgn first.")
    base = read_base()
    if args.mode == "initial":
        if not INITIAL_PGN.is_file():
            raise SystemExit("Initial mode requires pgn/initial.pgn. Put the complete initial-pool games in that file.")
        paths = [INITIAL_PGN]
        games = read_games(paths)
        if not games:
            raise SystemExit("pgn/initial.pgn contains no completed valid games.")
        names = {name for game in games for name in (game["white"], game["black"])}
        anchor = choose_stockfish_name(names, os.getenv("MCCR_ANCHOR_ENGINE", ""))
        bayes = run_bayeselo(paths, anchor, float(os.getenv("MCCR_ANCHOR_ELO", "3200")))
        missing = names - set(bayes)
        if missing:
            raise RuntimeError("BayesElo did not return ratings for: " + ", ".join(sorted(missing)))
        # Persist the initial pool as the frozen reference for later entrants.
        initial_ratings = {name: bayes[name]["rating"] for name in names}
        write_base(initial_ratings)
        rows = make_rows(games, bayes)
        note = f"BayesElo maximum-likelihood ratings; Stockfish anchor {anchor} = 3200. Initial pool calculated only from pgn/initial.pgn."
    else:
        if not INITIAL_PGN.is_file():
            raise SystemExit("Entrant mode requires pgn/initial.pgn to preserve the original reference pool.")
        if not base:
            raise SystemExit("No frozen reference ratings found in ratings/base_ratings.csv. Run initial mode first.")
        entrant_paths = [path for path in all_paths if path.name.lower() != "initial.pgn"]
        if not entrant_paths:
            raise SystemExit("Entrant mode needs a PGN other than initial.pgn, e.g. pgn/Caipora_3.8.pgn.")
        entrant_games = read_games(entrant_paths)
        all_games = read_games([INITIAL_PGN] + entrant_paths)
        if not entrant_games:
            raise SystemExit("No completed valid games found in entrant PGNs.")
        names_in_entrant_files = {name for game in entrant_games for name in (game["white"], game["black"])}
        newcomers = names_in_entrant_files - set(base)
        entrant = args.engine.strip() if args.engine.strip() else ""
        if entrant:
            if entrant not in newcomers:
                raise SystemExit(f"Selected entrant {entrant!r} is not an unranked player in the non-initial PGNs. Unranked names: {sorted(newcomers)}")
        else:
            if len(newcomers) != 1:
                raise SystemExit("Could not identify exactly one new engine in the non-initial PGNs. Add --engine with the exact PGN player name. Unranked names: " + ", ".join(sorted(newcomers)))
            entrant = next(iter(newcomers))
        if any(name not in base for name in names_in_entrant_files if name != entrant):
            raise SystemExit("Entrant PGNs contain additional unranked opponents. Each update should introduce one new engine against already-rated engines only.")
        all_names = {name for game in all_games for name in (game["white"], game["black"])}
        anchor = choose_stockfish_name(all_names, os.getenv("MCCR_ANCHOR_ENGINE", ""))
        bayes = run_bayeselo([INITIAL_PGN] + entrant_paths, anchor, float(os.getenv("MCCR_ANCHOR_ELO", "3200")))
        if entrant not in bayes:
            raise RuntimeError(f"BayesElo did not return a rating for new entrant {entrant!r}.")
        # Existing published ratings stay frozen; the new entrant's BayesElo estimate is aligned to Stockfish=3200.
        published = dict(base)
        published[entrant] = bayes[entrant]["rating"]
        write_base(published)
        rows = make_rows(all_games, bayes, fixed_ratings={name: rating for name, rating in base.items()}, entrant=entrant)
        note = f"BayesElo estimate for new entrant {entrant}; Stockfish anchor {anchor} = 3200. Previously published ratings remain frozen; only the new engine's rating is added."
    write_outputs(rows, note)
    print(f"BayesElo processed {len(games if args.mode == 'initial' else all_games)} games for {len(rows)} displayed engines.")
    print(f"Generated {OUT_HTML.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)}")

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        raise SystemExit(f"MCCR rating update failed: {exc}")
