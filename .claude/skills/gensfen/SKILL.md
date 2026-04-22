---
name: gensfen
description: Generate NNUE training positions (binpack) via YaneuraOu `gensfen`, then shuffle + optionally replace root sfen with qsearch leaf via `shuffle_kifu`.
---

# gensfen — teacher position generation

Produces `data/<name>/shuffled.bin` suitable as input to the `train` skill.

## Invocation

When the user runs `/gensfen`, use `AskUserQuestion` to interactively collect the required parameters before executing. Do NOT assume defaults for `<name>` or `--variant` — always ask. See the "Interactive parameter collection" section below.

## Directory layout

All engine-related assets live under `engines/`:

```
engines/
  eval/hkp768/nn.bin        ← teacher eval files
  eval/hkp256/nn.bin
  eval/kp256/nn.bin
  book/user_book1.db         ← opening book
  book/standard_book.db
  YaneuraOu-HalfKP_768x2-16-64_learn  ← evallearn binaries
  ...
```

Output goes to `data/<name>/`:

```
data/<name>/
  raw/gen_0.bin ...          ← gensfen raw output
  shuffled.bin               ← final shuffled output
```

## Interactive parameter collection

Use `AskUserQuestion` to gather parameters. Ask up to 4 questions at a time.

### Round 1: basic settings

1. **Variant** — which engine variant to use?
   - Detect available binaries under `engines/*_learn` and available eval dirs under `engines/eval/`.
   - Only show variants where BOTH the binary AND the eval dir exist.
   - Options: `hkp768`, `hkp256`, `kp256`, etc. (only those actually available)
2. **Name** — output directory name under `data/`.
   - Suggest a sensible default based on variant and depth, e.g. `hkp768_d9`
3. **Count** — how many positions to generate?
   - Options: `1M` (test), `100M` (small), `800M` (standard), custom
4. **Depth** — search depth.
   - Options: `6` (fast), `9` (standard, recommended), `12` (deep), custom

### Round 2: advanced settings (optional)

Only ask if the user picked "Other" or if defaults need confirmation:

- **FV_SCALE**: auto-resolved from variant (`hkp768`=40, `hkp256`=20, `kp256`=16, others=16)
- **Book**: default `engines/book/user_book1.db`
- **ApplyQSearch**: default `true`

## Engine resolution

`--variant` maps to a binary under `engines/`:

| variant | binary | eval dir | FV_SCALE |
|---|---|---|---|
| `kp256` | `engines/YaneuraOu-K-P_256-32-32_learn` | `engines/eval/kp256` | 16 |
| `hkp256` | `engines/YaneuraOu-HalfKP_256x2-32-32_learn` | `engines/eval/hkp256` | 20 |
| `hkp512` | `engines/YaneuraOu-HalfKP_512x2-16-32_learn` | `engines/eval/hkp512` | 16 |
| `hkp768` | `engines/YaneuraOu-HalfKP_768x2-16-64_learn` | `engines/eval/hkp768` | 40 |
| `hkp1024` | `engines/YaneuraOu-HalfKP_1024x2-8-32_learn` | `engines/eval/hkp1024` | 16 |
| `hkp1024_64` | `engines/YaneuraOu-HalfKP_1024x2-8-64_learn` | `engines/eval/hkp1024_64` | 16 |

If the binary does not exist, build it first:
```bash
scripts/build_yaneuraou.sh <variant> --build evallearn
```

## Pre-flight checks

Before executing, verify ALL of the following. If any check fails, report the issue and offer to fix it (e.g., build the binary, or ask for the eval file):

1. Engine binary exists: `engines/<binary>`
2. Eval dir exists and contains `nn.bin`: `engines/eval/<variant>/nn.bin`
3. Book file exists (if using book): `engines/book/user_book1.db`
4. Output dir does not already contain data (warn if overwriting)

## Execution template

```bash
ENGINE_BIN="engines/<binary-from-variant-table>"
EVAL_DIR="engines/eval/<variant>"
BOOK_DIR="engines/book"
BOOK_FILE="user_book1.db"

# Create output directory
mkdir -p data/<name>/raw

# Step 1: gensfen
"$ENGINE_BIN" <<EOF
setoption name EvalDir value $EVAL_DIR
setoption name FV_SCALE value <fv-scale>
setoption name BookDir value $BOOK_DIR
setoption name BookFile value $BOOK_FILE
setoption name Threads value $(nproc)
setoption name USI_Hash value 8192
isready
gensfen depth <depth> loop <count> save_every 1000000 output_file_name data/<name>/raw/gen
quit
EOF

# Step 2: shuffle + qsearch leaf
"$ENGINE_BIN" <<EOF
setoption name EvalDir value $EVAL_DIR
setoption name FV_SCALE value <fv-scale>
setoption name BookDir value $BOOK_DIR
setoption name BookFile value $BOOK_FILE
setoption name Threads value $(nproc)
setoption name USI_Hash value 8192
setoption name KifuDir value data/<name>/raw
setoption name ShuffledKifuDir value data/<name>
setoption name ApplyQSearch value <qsearch>
isready
shuffle_kifu
quit
EOF
```

## Execution notes

- gensfen is CPU-bound and long-running — always launch with `run_in_background` and monitor via `Monitor`.
- `save_every 1000000` splits output into 1M-record chunks (`gen_1`, `gen_2`, ...). This enables progress tracking (count files × 40MB) and resumability. `shuffle_kifu` reads all `.bin` files in `KifuDir`, so chunked output works transparently.
- `shuffle_kifu` needs ~2x the raw data size as temp space.
- Binpack record = 40 bytes; validate expected file size (`count * 40`).
- For fleet-distributed generation across multiple hosts, delegate to the `nnue-fleet` skill instead.
