# MCCR starter

## Included
- `mccr_rating.py`: creates a CCRL-inspired HTML rating table and CSV from PGNs.
- `.github/workflows/mccr-rating.yml`: GitHub Actions automation.
- `pgn/`: place PGN files here.
- `ratings/base_ratings.csv`: frozen ratings used in entrant mode.

## Important honesty about the estimator
This starter does NOT yet reproduce CCRL/BayesElo. It includes:
- `initial`: connected-pool logistic score ratings, anchored at Stockfish = 3000 if Stockfish appears in the PGN; otherwise the highest fitted engine is anchored at 3000.
- `entrant`: estimates only the new engine's performance rating against frozen opponent ratings; existing opponents' published ratings are left unchanged.

The workflow downloads and compiles a public BayesElo source mirror as a reference step, but the current Python script does not invoke it. Do not advertise these starter ratings as BayesElo ratings until the BayesElo command pipeline is integrated and validated.

## Initial 11-engine math
11 engines round-robin, 50 games per unique pairing:
- 55 pairings
- 2,750 actual games
- 500 games per engine
- Sum of per-engine game counts = 5,500 because every game is counted for both players.

## Use
1. Copy these files into your MCCR GitHub repository.
2. Upload PGNs under `pgn/`.
3. For the initial pool, run Actions -> MCCR Rating Update -> mode `initial`.
4. For a newcomer, fill `ratings/base_ratings.csv` with the established ratings, upload the newcomer's PGN batch, then run mode `entrant` and provide the exact PGN player name.
5. Download the Actions artifact or enable GitHub Pages to publish `index.html`.

## Frozen ratings CSV format
```csv
engine,rating
Stockfish 19 64-bit,3000
Reckless 0.9.0 64-bit,2980
```

Names must match the PGN player names. Do not upload duplicate PGNs: every `.pgn` under `pgn/` is included in the calculation.
