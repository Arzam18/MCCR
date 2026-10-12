# MCCR — Mobile Computer Chess Rating

MCCR is an independent rating list for chess engines tested on Android devices under the MCCR test conditions. It is inspired by computer-chess rating lists such as CCRL, but its ratings are an **internal MCCR scale** and must not be compared directly with CCRL ratings.

## Rating method and scale

- **Calculator:** BayesElo, built from the official source archive published by Rémi Coulom.
- **Anchor:** the Stockfish engine name present in the PGN is set to **3200 MCCR Elo**. Other engines are rated relative to that anchor; 3200 is not a claim about Stockfish's CCRL rating.
- **Initial list:** all games in `pgn/initial.pgn` are used. The number of engines and games is flexible; the file is not required to contain exactly 2,750 games. The initial 11-engine plan may use 2,750 games if all 55 pairings play 50 games, but MCCR does not hard-code that total.
- **New entrants:** after the initial list is established, each new engine gets its own PGN file (for example `pgn/Caipora_3.8.pgn`) containing games against already-rated engines. In entrant mode, BayesElo processes the initial PGN plus all entrant PGNs so the newcomer is rated on the same scale. Previously published ratings are kept frozen in the public table; only the newcomer is added to the frozen reference list. This is an intentional MCCR policy, not a full-pool recalculation policy.
- **Table:** rating, uncertainty (+/−), score, average opponent, draw percentage, games, wins, draws, losses, number of opponents, and status.

## Test conditions

MCCR is intended to report engine performance under its defined Android tournament conditions, currently 30 seconds plus 0.5 seconds increment and a two-ply opening (one move by each side), unless a future README update explicitly changes those conditions. Record the exact engine name/version in PGN headers and avoid mixing different versions under one name.

## Repository layout

```text
.github/workflows/mccr-rating.yml
mccr_rating.py
pgn/
  initial.pgn
  Caipora_3.8.pgn       # example of a later entrant PGN
ratings/
  base_ratings.csv      # frozen published reference ratings
  mccr_ratings.csv      # generated table data
index.html              # generated CCRL-inspired rating page
```

## First setup and initial list

1. Put the complete initial-pool PGN in `pgn/initial.pgn`. The PGN must contain standard `White`, `Black`, and `Result` headers. Use the exact Stockfish player name you want anchored at 3200.
2. In GitHub, open **Actions → MCCR Rating Update → Run workflow** and select `initial`.
3. The workflow installs `python-chess`, downloads and compiles official BayesElo, validates the PGN, calculates ratings, generates the HTML and CSV files, and commits the outputs. A failed BayesElo build or calculation fails the workflow rather than falling back to another estimator.
4. Review `index.html`, `ratings/mccr_ratings.csv`, and `ratings/base_ratings.csv`. The base CSV is the frozen reference list used for later entrants.

The initial file can contain any number of valid completed games and any connected pool of engines. Ratings based on very few games will have high uncertainty and should be treated as provisional.

## Add one engine after the initial list

1. Add a new PGN file under `pgn/`, e.g. `pgn/Caipora_3.8.pgn`. Do **not** overwrite `initial.pgn`.
2. The entrant PGN should contain the new engine and already-rated opponents only. Its exact PGN player name must not already exist in `ratings/base_ratings.csv`.
3. Open **Actions → MCCR Rating Update → Run workflow**, select `entrant`, and optionally enter the exact new engine name. Leave it blank to auto-detect when exactly one new engine name appears in non-initial PGNs.
4. BayesElo calculates the new entrant's rating from `initial.pgn` and all entrant PGNs, using Stockfish=3200 as the anchor. Existing published ratings remain frozen in the public list; the new engine is appended to `base_ratings.csv` for future entrants.

Each entrant PGN should be unique. Do not upload duplicate games or duplicate copies of the same PGN because they would be counted twice. When a later engine version is tested, use a distinct exact engine name/version.

## Outputs

- `index.html`: CCRL-inspired rating list with W/D/L columns.
- `ratings/mccr_ratings.csv`: machine-readable table.
- `ratings/base_ratings.csv`: frozen reference ratings for the entrant policy.
- GitHub Actions artifact `mccr-rating-results`: downloadable copies of the generated files.

## Important methodology note

BayesElo estimates relative ratings from the submitted game results. In entrant mode, MCCR intentionally freezes previously published ratings rather than replacing them with new full-pool estimates. Therefore the newcomer estimate is BayesElo-based, while the overall list is a **frozen-reference list** over time. This preserves the MCCR rule that new entrants do not move established engines' published ratings.

BayesElo is distributed under the GNU General Public License. The workflow downloads the official source archive at build time; it does not silently use the temporary logistic calculator from the starter version.
