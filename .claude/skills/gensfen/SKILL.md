---
name: gensfen
description: Generate NNUE training positions (binpack) via YaneuraOu `gensfen`, then shuffle + optionally replace root sfen with qsearch leaf via `shuffle_kifu`.
---

# gensfen — teacher position generation

Produces `data/<name>/shuffled.bin` suitable as input to the `train` skill.

## Prerequisites

- YaneuraOu binary with `evallearn` + `shuffle_kifu` (path read from `$YANEURAOU_BIN`)
- An existing eval directory to use as teacher (e.g. `eval/hkp768`, `eval/kp256`)
- Opening book if desired (`book/user_book1.db`)

## Standard flow

1. **gensfen** — run teacher search from balanced openings, write raw `kifu/*.bin`.
2. **shuffle_kifu** — shuffle 2-pass with `ApplyQSearch=true` to replace each root sfen with its qsearch leaf (see `docs/train/qsearch_leaf_policy.md`).
3. Output lands at `data/<name>/shuffled.bin`.

## Usage

```
/gensfen <name> [--depth 9] [--count 800M] [--teacher eval/hkp768] [--fv-scale 40]
```

Arguments (all optional, sensible defaults):

| flag | default | meaning |
|---|---|---|
| `<name>` | required | output dir under `data/` |
| `--depth` | 9 | YaneuraOu search depth |
| `--count` | `800M` | target positions (suffix `K`/`M`/`B`) |
| `--teacher` | `eval/hkp768` | teacher eval dir |
| `--fv-scale` | `40` | matches teacher's FV_SCALE |
| `--qsearch` | `true` | apply qsearch-leaf replacement in shuffle |
| `--book` | `book/user_book1.db` | opening book |

## Execution template

```bash
# Step 1: gensfen
"$YANEURAOU_BIN" <<EOF
setoption name EvalDir value <teacher>
setoption name FV_SCALE value <fv-scale>
setoption name BookFile value <book>
setoption name Threads value $(nproc)
setoption name Hash value 8192
isready
gensfen depth <depth> loop <count> output_file_name data/<name>/raw/gen
quit
EOF

# Step 2: shuffle + qsearch leaf
"$YANEURAOU_BIN" <<EOF
setoption name EvalDir value <teacher>
setoption name FV_SCALE value <fv-scale>
setoption name KifuDir value data/<name>/raw
setoption name ShuffledKifuDir value data/<name>
setoption name ApplyQSearch value <qsearch>
isready
shuffle_kifu
quit
EOF
```

## Notes

- gensfen is CPU-bound and long-running — always launch with `run_in_background` and monitor stdout line count via `Monitor`.
- `shuffle_kifu` needs ~2× the raw data size as temp space.
- Binpack record = 40 bytes; validate expected file size (`count * 40`).
- For fleet-distributed generation across multiple hosts, delegate to the `nnue-fleet` skill instead.