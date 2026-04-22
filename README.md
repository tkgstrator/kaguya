# kaguya — Shogi NNUE Training Pipeline

End-to-end toolkit for generating training positions, training, and evaluating Shogi NNUE (Efficiently Updatable Neural Network) models.

## Overview

Built on YaneuraOu V8.50 with tanuki-dr5 compatible gensfen / shuffle_kifu pipeline. Driven interactively via Claude Code slash commands (`/gensfen`, `/train`, `/eval`).

## Pipeline

```
/gensfen                          /train                        /eval
   |                                 |                             |
   v                                 v                             v
YaneuraOu gensfen (depth search) PyTorch Lightning            YaneuraOu matches
   |                                 |                             |
   v                                 v                             v
shuffle_kifu (ApplyQSearch)      nn.bin output                 Elo +/- 95% CI
   |
   v
data/<name>/shuffled.bin
```

## Directory Layout

```
engines/
  eval/{kp256,hkp256,hkp768}/nn.bin   teacher eval files
  book/user_book1.db                   opening book
  YaneuraOu-*_learn                    evallearn binaries
vendor/
  YaneuraOu/                           V8.50 (learn branch, tanuki-dr5 compatible)
scripts/
  build_yaneuraou.sh                   build helper (6 variants)
  compare_gensfen.py                   gensfen output comparison script
data/
  <name>/raw/                          gensfen raw output
  <name>/shuffled.bin                  shuffled + qsearch leaf replacement
docs/
  plans/                               migration plans and change tracking
  train/                               training policy documentation
```

## Supported Variants

| variant | architecture | FV_SCALE | eval available |
|---|---|---|---|
| `kp256` | K-P 256-32-32 | 16 | yes |
| `hkp256` | HalfKP 256x2-32-32 | 20 | yes |
| `hkp768` | HalfKP 768x2-16-64 | 40 | yes |
| `hkp512` | HalfKP 512x2-16-32 | 16 | — |
| `hkp1024` | HalfKP 1024x2-8-32 | 16 | — |
| `hkp1024_64` | HalfKP 1024x2-8-64 | 16 | — |

## Quick Start

### Build Engine

```bash
scripts/build_yaneuraou.sh hkp768 --build evallearn
```

### Generate Training Positions

```bash
# From Claude Code
/gensfen
# → interactively select variant, count, depth
# → runs gensfen + shuffle_kifu (ApplyQSearch=true) automatically
```

### Manual Execution

```bash
engines/YaneuraOu-HalfKP_768x2-16-64_learn <<EOF
setoption name EvalDir value engines/eval/hkp768
setoption name FV_SCALE value 40
setoption name BookDir value engines/book
setoption name BookFile value user_book1.db
setoption name Threads value $(nproc)
setoption name USI_Hash value 8192
isready
gensfen depth 9 loop 1000000 save_every 1000000 output_file_name data/run1/raw/gen
quit
EOF
```

## YaneuraOu V8.50 Modifications

Changes made for tanuki-dr5 compatibility:

- **TT (transposition table)**: replaced `TTData`/`TTWriter` tuple API with `TTEntry*` + `bool& found` API
- **TT memory management**: introduced `LargeMemory` RAII class
- **Constants**: `VALUE_SUPERIOR`=28000, `VALUE_MAX_EVAL`=27000, `VALUE_KNOWN_WIN`=30744, `DEPTH_ENTRY_OFFSET`=-7
- **gensfen**: added seed parameter, unified write_minply default (16)
- **shuffle_kifu**: ported tanuki-dr5 `ShuffleKifu` + `ApplyQSearch`
- **Crash fix**: resolved TT memory corruption caused by `is_ready(true)` in `MultiThink::go_think()`

See `docs/plans/gensfen_parity_with_tanuki.md` for detailed change tracking.

## Requirements

- Ubuntu 24.04 / g++ 13.3
- AVX2-capable CPU
- OpenMP (libgomp1)

## License

[GPL-3.0](LICENSE) — following [YaneuraOu](https://github.com/yaneurao/YaneuraOu) upstream license.
