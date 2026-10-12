# MCCR — Mobile Computer Chess Rating

**MCCR Ratinglist**

**MCCR Condition:**
- **Thread:** 1
- **TC:** 30s + 0.5s
- **Hash:** 16 MB
- **Ponder:** Off
- **Tablebase:** Disabled
- **Hardware:** ARM64-v8.2a, Android 16, Samsung Galaxy A16 5G, processor 2.2–2.4 GHz
- **Chess GUI:** ChessEngineTournament (CET)
- **Opening book:** UHO 2022, 6 moves, +1.20 / +1.29

**Update:** Created MCCR.

**Next TestRun:** Initial Top 1–11 engines.

**Rating lists:** [Open the MCCR Rating List](index.html) · [Download the rating data (CSV)](ratings/mccr_ratings.csv)

---

MCCR is an independent rating list for chess engines tested on Android. Its table design is inspired by CEGT's compact rating-list layout. MCCR ratings use an internal scale anchored to the Stockfish player in the initial pool at **3200 MCCR Elo**; they are not directly comparable to CCRL or CEGT ratings.

## Rating table

The workflow generates `index.html` with the CEGT-inspired columns **no, Program, Elo, +, −, Games, Score, Av.Op., Draws**. The CSV also preserves wins, draws, losses, number of opponents, status, and other rating data.

## Important behavior

- **Permanent game history:** `ratings/games.jsonl` stores unique completed games in machine-readable form. Ratings and W/D/L statistics are calculated from this database, not only from currently uploaded PGNs.
- **Delete PGNs after success:** delete a source PGN only after the workflow has successfully committed the updated database. Its games remain stored.
- **Duplicate protection:** game fingerprints prevent the same PGN game being counted twice on later uploads.
- **Add an engine:** use workflow action `add`, provide the exact engine player name in the PGN, and choose the display name for the table.
- **Update a version:** use `update`, provide the new version's exact PGN player name, its display name, and the existing displayed entry to replace. Historical results are retained under that engine identity and combined with new results.
- **Frozen ratings:** after initialization, only the explicitly added or updated engine receives a newly calculated rating. Existing published ratings remain frozen, though their game statistics can change as more games are imported. This is MCCR's stability policy, not a standard full-pool recalculation.
- **BayesElo anchor:** the Stockfish entry chosen from the initial pool is fixed at 3200. Updating that anchor cannot give it a different published rating while it remains the anchor.

## First run — initialize the initial pool

1. Place the initial test PGN at `pgn/initial.pgn`.
2. Open **Actions → MCCR Rating Update → Run workflow**.
3. Select action `initial`. The initial file may contain any number of completed games.
4. Confirm the run succeeds and commits `ratings/games.jsonl`, `ratings/engine_aliases.json`, `ratings/mccr_config.json`, the CSV files, and `index.html`.

The first Stockfish player name found in the initial PGN is used as the 3200 anchor. The initial action cannot overwrite an already initialized database.

## Add a new engine

1. Put the new engine's PGN under `pgn/` and commit it. Its opponents must already be registered in MCCR.
2. Run the workflow with action `add`.
3. Enter the exact PGN player name and the desired display name.
4. Confirm the workflow succeeds. It imports available PGNs, skips already recorded games, and updates the permanent database and rating list.

## Update an existing engine

1. Upload the new version's PGN under `pgn/` and commit it.
2. Run the workflow with action `update`.
3. Enter the new version's exact PGN player name, the new display name, and the exact current display name to replace.
4. Confirm the updated row replaces the previous displayed entry and the database commit succeeds.

For example, updating `Stockfish 19` to `Stockfish 19.1` retains the old version's games under the same MCCR identity and combines them with the new version's games. This is a deliberate cumulative-version policy; it does not measure the new binary in isolation.

## Repository files

- `.github/workflows/mccr-rating.yml` — GitHub Actions workflow
- `mccr_rating.py` — imports games, calculates ratings, and generates the table
- `pgn/` — temporary upload location for PGNs
- `ratings/games.jsonl` — permanent cumulative game database
- `ratings/engine_aliases.json` — PGN names mapped to stable engine identities
- `ratings/mccr_config.json` — engine display names and anchor configuration
- `ratings/base_ratings.csv` — frozen rating references
- `ratings/mccr_ratings.csv` — full machine-readable rating table
- `index.html` — generated public rating list

**Important:** never delete `ratings/games.jsonl`, `ratings/engine_aliases.json`, or `ratings/mccr_config.json` if you want to preserve rating history. Remove uploaded PGNs only after their games have been imported and the database has been committed successfully.
