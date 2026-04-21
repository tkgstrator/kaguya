---
name: eval
description: Evaluate a trained NNUE checkpoint by playing matches against a fixed baseline engine (default KP256 2019) and report W/L/D + Elo ±95% CI.
---

# eval — rating evaluation via match play

Converts a training checkpoint to `.nnue`, launches YaneuraOu vs a baseline engine for N games from balanced openings, and reports Elo.

## Prerequisites

- A checkpoint from the `train` skill (`.ckpt`) or an existing `.nnue` file
- Baseline engine + eval dir (default: `engine/YaneuraOu-K-P_256-32-32` + `eval/kp256`)
- YaneuraOu binary matching the challenger architecture (`$YANEURAOU_BIN`)
- Balanced opening set at `data/balanced_ply32.sfen`
- `ordo` for Elo computation

## Usage

```
/eval <ckpt_or_nnue> [options]
```

| flag | default | meaning |
|---|---|---|
| `<ckpt_or_nnue>` | required | `.ckpt` (auto-serialize) or `.nnue` |
| `-m / --baseline` | `kp256` | baseline model key |
| `-g / --games` | `1000` | total games (each opening played from both sides) |
| `-d / --depth` | `0` | fixed depth; `0` → use byoyomi |
| `-b / --byoyomi` | `500` | ms/move |
| `-t / --threads` | `4` | threads per engine |
| `-H / --hash` | `1024` | USI Hash MB |
| `-c / --concurrency` | `32` | parallel games |
| `--openings` | `data/balanced_ply32.sfen` | opening book (sfen list) |

## Execution template

```bash
uv run python scripts/eval_model.py <ckpt_or_nnue> \
  -m <baseline> -g <games> -d <depth> -b <byoyomi> \
  -t <threads> -H <hash> -c <concurrency>
```

Internally this:
1. If input is `.ckpt`, calls `scripts/serialize.py` to produce `.nnue`.
2. Builds a c-chess-cli–style match schedule: each opening played from both colors.
3. Invokes two YaneuraOu processes per game, collects PGN-equivalent results.
4. Feeds results to `ordo` → Elo ± CI95.

## Output format

```
challenger: <path> (arch=<arch>, step=<step>, positions=<pos>)
opponent:   <baseline> (eval=<dir>)
games:      <games>   byoyomi: <byoyomi>ms  threads: <threads>  concurrency: <concurrency>
W / L / D:  <W> / <L> / <D>   (winrate <p>%)
Elo:        <elo> ± <ci> (95% CI)
```

## Baselines

| key | engine | eval |
|---|---|---|
| `kp256` | `engine/YaneuraOu-K-P_256-32-32` | `eval/kp256` |
| `hkp256` | `engine/YaneuraOu-HKP-256-32-32` | `eval/hkp256` |
| (add more as baselines are registered) | | |

## Notes

- Rating signal at 1000 games is roughly ±22-25 Elo CI; for noisy decisions go to 3000 games.
- If evaluating many checkpoints from one run, use `model-eval` skill (pairwise) instead of calling `/eval` repeatedly.
- For ckpts that are not yet overfit, the curve usually peaks mid-run — sample 5-10 evenly-spaced checkpoints before concluding.
- Elo >0 against the 2019 KP256 baseline is the minimum bar for calling a run "working"; KP256 has peaked at +182, HKP256 at +400 Elo on this setup (see `docs/train/evaluation_trained_model.md`).