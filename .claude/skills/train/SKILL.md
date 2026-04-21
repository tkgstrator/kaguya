---
name: train
description: Train a NNUE model (KP / HKP / BHKP / FMHKP / MHKP variants) with PyTorch Lightning on the prepared binpack.
---

# train — NNUE model training

Launches `scripts/train.py` on a prepared binpack (`data/<dataset>/shuffled.bin`) and writes checkpoints + TensorBoard logs under `runs/<run>/`.

## Prerequisites

- Binpack at `data/<dataset>/shuffled.bin` (produced by `/gensfen`)
- `scripts/train.py` and NNUE model code imported from `nnue-pytorch` (to be copied in later; skill assumes the canonical entry point)
- GPU available (A100 class recommended; skill also works on smaller GPUs by shrinking batch size)
- `.env` loaded for wandb credentials (`WANDB_API_KEY`, `WANDB_BASE_URL`, Cloudflare Access headers)

## Usage

```
/train <run_name> --arch <kp|hkp|bhkp|fmhkp|mhkp> --data <dataset> [options]
```

| flag | default | meaning |
|---|---|---|
| `<run_name>` | required | output dir under `runs/` |
| `--arch` | `kp` | feature set / architecture |
| `--data` | required | dataset dir under `data/` |
| `--l1` | `256` | L1 width (256 / 512 / 1024) |
| `--batch-size` | `65536` | per-step positions |
| `--lr` | `3.5e-3` | initial LR (scale linearly with batch_size / 16384) |
| `--epochs` | `800` | max virtual epochs |
| `--num-workers` | `128` | DataLoader workers |
| `--gpus` | `1` | number of GPUs (DDP kicks in if >1) |
| `--resume` | — | checkpoint path to resume from |

## Execution template

```bash
set -a; source .env; set +a

OMP_NUM_THREADS=16 \
uv run python scripts/train.py \
  data/<dataset>/shuffled.bin \
  --arch <arch> --l1 <l1> \
  --batch-size <batch-size> --lr <lr> \
  --num-workers <num-workers> --epochs <epochs> \
  --default_root_dir runs/<run_name> \
  --network-save-period 1 \
  --wandb-project nnue-pytorch --wandb-name <run_name>
```

## Hyperparameter defaults (validated on KP256)

These come from `docs/train/tuning.md`. Keep them unless there is a concrete reason to deviate.

- optimizer: **Ranger21** (betas=(0.9, 0.999), eps=1e-7, weight_decay=0)
- scheduler: **StepLR** (step_size=1 epoch, gamma=0.992)
- lambda (teacher vs win-rate mix): **1.0** (teacher score only)
- epoch_size: 100M positions, val_size: 1M positions
- seed: 42
- `torch.compile` backend: `inductor`

## Monitoring

- TensorBoard: `runs/<run_name>/lightning_logs/version_*/events.out.tfevents.*`
- wandb: `$WANDB_BASE_URL/<entity>/nnue-pytorch/runs/<run_id>`
- Use the `wandb-check` skill for health diagnostics (loss trend, val-train gap, throughput, divergence).

## Notes

- Always start with `run_in_background` and attach `Monitor` — a full KP256 run is ~5.7 hours on 1×A100.
- If throughput is low (<100 it/s on A100, batch 16384), suspect DataLoader: see `docs/train/tuning.md` for the `ParallelBinSfenInputStream` history.
- Checkpoints land at `runs/<run_name>/default/version_*/checkpoints/*.ckpt`. Convert to `.nnue` via `scripts/serialize.py` (to be added with nnue-pytorch import).
- Delegate multi-run sweeps or multi-GPU DDP sizing decisions to the `trainer` agent.