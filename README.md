# MCCR — Mobile Computer Chess Rating

MCCR is an independent rating list for chess engines tested on Android. It uses BayesElo and an internal scale anchored to the Stockfish player in the **initial pool at 3200 MCCR Elo**. MCCR ratings are not directly comparable to CCRL ratings.

## Important behavior

- **Persistent results:** `ratings/games.jsonl` stores every unique completed game in machine-readable form. Ratings and W/D/L statistics are calculated from this database, not just from the PGNs currently in `pgn/`.
- **Safe PGN deletion:** after a successful workflow run commits `ratings/games.jsonl`, the source PGN may be deleted from the repository. Its games remain in the database.
- **Duplicate protection:** every imported game has a fingerprint. If the same PGN/game is uploaded again, it is skipped rather than counted twice.
- **New engine:** a new engine gets a new identity and a rating based on its games plus all historical games in the cumulative database.
- **Engine update:** choose `update`, enter the exact new PGN player name, set the new display name, and enter the current display name to replace. The new version is linked to the existing engine identity, so its old-version results and new-version results are combined. The old row is renamed/replaced, not duplicated.
- **Frozen ratings:** after the initial list, only the engine explicitly added or updated gets a newly calculated published rating. Other established ratings remain frozen, although their cumulative games/W-D-L statistics continue to grow. This is MCCR's chosen policy, not a full-pool recalculation.
- **Full rating table:** `ratings/mccr_ratings.csv` and `index.html` include rank, engine, rating, uncertainty (+/−), score, average opponent, draw percentage, games, wins, draws, losses, opponents, and status.

## Repository layout

```text
.github/workflows/mccr-rating.yml
mccr_rating.py
pgn/initial.pgn
pgn/<uploaded-engine-test>.pgn
ratings/base_ratings.csv       # frozen published rating reference
ratings/engine_aliases.json    # raw PGN player names -> stable engine identities
ratings/games.jsonl            # permanent cumulative game database
ratings/mccr_config.json       # engine display names and initial anchor
ratings/mccr_ratings.csv       # full generated table
index.html                     # full generated rating page
```

## First run: initial pool

1. Put the initial pool PGN at `pgn/initial.pgn`.
2. Open **Actions → MCCR Rating Update → Run workflow**.
3. Select `initial` and run it. This action can only initialize an empty MCCR history; it cannot overwrite an already initialized database.
4. Confirm that the workflow commits `ratings/games.jsonl`, `ratings/engine_aliases.json`, `ratings/mccr_config.json`, the base CSV, full rating CSV, and `index.html`.

The initial PGN can contain any number of completed games and engines. The first Stockfish player name found is the 3200 anchor.

## Add a new engine

1. Upload its PGN under `pgn/` and commit it. The PGN should contain the new engine and opponents already registered in MCCR.
2. Run the workflow with action `add`.
3. **Engine:** exact `White`/`Black` PGN header name for the new engine.
4. **Display name:** the label to show in the published table.
5. Run the workflow. It imports all available PGNs but skips games already in the permanent database.

## Update an existing engine/version

For example, to replace the published `Stockfish 19` entry with `Stockfish 19.1`:

1. Upload a PGN containing games for the new version against already registered engines.
2. Run the workflow with action `update`.
3. **Engine:** exact new PGN player name, e.g. `Stockfish 19.1`.
4. **Display name:** e.g. `Stockfish 19.1`.
5. **Replace existing:** the exact current display name, e.g. `Stockfish 19`.

The new PGN name is mapped to the existing stable identity. Old-version games remain attached to that identity, so BayesElo rates the combined historical record plus the new version's games. The published row is renamed to the new display name. The old games are not deleted. Other established ratings remain frozen by design.

If the updated engine is the actual anchor engine selected during initial setup, it remains the 3200 anchor; an anchor cannot simultaneously be fixed at 3200 and rated at another number.

## Removing uploaded PGNs

Only delete a source PGN **after** the workflow succeeds and the commit contains the updated `ratings/games.jsonl`. Future runs use the database even if the original PGN files have been removed. Keep the database and its identity/config files in the repository; deleting them would erase MCCR's stored history.

## Method note

BayesElo calculates the updated engine's rating from the cumulative game database, with the initial Stockfish anchor fixed at 3200. Existing published ratings are frozen except for the one engine explicitly added or updated. This intentionally prioritizes historical list stability over conventional full-pool rating recalculation.
