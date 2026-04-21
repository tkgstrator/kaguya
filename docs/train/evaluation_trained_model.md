# 学習済みモデルの評価レポート

## 1. 学習データ

- **Hao Depth9 Shuffled QSearch** (shuffled d9 + qsearch 末端スコア)
- サイズ 324 GB、train:val = 99:1 分割、train.bin ≈ 8 B positions
- binpack 形式 (40 bytes / position)

## 2. 学習設定

- 実装: nnue-pytorch (本リポジトリ、`scripts/train.py` デフォルト)
- positions seen = step × batch_size = step × 16384
- 対象: HKP256 (HalfKP, L1=256) / KP256 (KP, L1=256)

### 2.1 ハイパーパラメータ

| 項目 | 値 | 意味 |
|---|---|---|
| optimizer | Ranger21 | AdamW ベース (betas=(0.9, 0.999), eps=1e-7, weight_decay=0, using_gc=False) |
| scheduler | StepLR | step_size=1 epoch, gamma=0.992 (epoch 毎に lr × 0.992) |
| lr | 8.75e-4 | 初期学習率 |
| batch_size | 16,384 | 1 step あたりの局面数 |
| epochs | 400 | 仮想 epoch 上限 (実際は max_time / save_top_k で前後する) |
| epoch_size | 100,000,000 | 1 仮想 epoch あたりの train positions |
| val_size | 1,000,000 | 1 validation パスあたりの positions |
| save_steps | 6,000 | ckpt 保存間隔 (step 単位) |
| eval_steps | 15,000 | balanced + 100-game eval の間隔 |
| val_steps | 500 | validation loss 計算の間隔 |
| lambda | 1.0 | mix ratio (win-rate vs teacher score)、1.0 は teacher score 100% |
| gamma | 0.992 | lr 減衰率 |
| seed | 42 | 乱数 seed |
| compile_backend | inductor | `torch.compile` backend |

### 2.2 計算環境

| 項目 | 値 | 備考 |
|---|---|---|
| GPU | A100 1台 | 単一 GPU で学習 (DDP 未使用) |
| num_workers | 1 | DataLoader のワーカスレッド数 |
| torch threads | auto (-1) | `torch.set_num_threads(-1)` により OMP が自動決定 |
| データ形式 | binpack | mmap + 複数 reader で OS page cache を共有 |

## 3. 評価設定

```bash
uv run python scripts/eval_model.py <ckpt> \
  -m kp256 -g 1000 -d 0 -b 500 -t 4 -H 1024 -c 32
```

- 対戦相手 (`-m kp256`): KP256(2019)
    - engine: `engine/YaneuraOu-K-P_256-32-32`
    - eval: `eval/kp256`
- 開始局面: `data/balanced_ply32.sfen` (32 手目までの互角局面集)
- 各局面につき先後を入れ替えて 2 局プレイ

| 項目 | 値 | 意味 |
|---|---|---|
| `-m` | `kp256` | 対戦相手モデル名 |
| `-g` | 1000 | 対局数 |
| `-d` | 0 | 固定深さ (0 で byoyomi 制に切替) |
| `-b` | 500 | byoyomi ms/move |
| `-t` | 4 | Threads / engine |
| `-H` | 1024 | USI Hash MB / engine |
| `-c` | 32 | 並列対局数 |

## 4. 結果

### 4.1 HKP256 vs KP256(2019)

| step | positions | W-L-D | Elo ± CI95 |
|---:|---:|---:|---:|
| 312,000 | 5.11 B | 875-120-5 | +342.04 ± 32.65 |
| 624,000 | 10.22 B | 905-88-7 | +398.76 ± 36.95 |
| 1,254,000 | 20.55 B | 901-96-3 | +386.58 ± 36.14 |

5 B positions 程度で +340 Elo を確保し、10 B positions 付近 (+400 Elo) でピーク、
それ以降は頭打ち、または軽微な劣化の傾向。

### 4.2 KP256 vs KP256(2019)

| step | positions | W-L-D | Elo ± CI95 |
|---:|---:|---:|---:|
| 318,000 | 5.21 B | 648-344-8 | +109.07 ± 22.50 |
| 366,000 | 6.00 B | 671-324-5 | +125.78 ± 22.90 |
| 462,000 | 7.57 B | 664-328-8 | +121.46 ± 22.76 |
| 654,000 | 10.72 B | 663-336-1 | +117.94 ± 22.77 |
| 1,032,000 | 16.91 B | 703-292-5 | +151.76 ± 23.55 |
| 1,788,000 | 29.29 B | 719-279-2 | +164.07 ± 23.95 |
| 2,544,000 | 41.68 B | 731-265-4 | +175.44 ± 24.28 |
| 2,730,000 | 44.73 B | 738-257-5 | +182.16 ± 24.48 |
| 2,772,000 | 45.40 B | 737-259-4 | +180.80 ± 24.45 |
| 2,820,000 | 46.20 B | 717-280-3 | +162.78 ± 23.90 |
| 2,916,000 | 47.78 B | 701-295-4 | +149.68 ± 23.51 |

5 B positions 程度で +100 Elo を安定して確保し、45 B positions 付近 (+182 Elo) でピーク、
それ以降は頭打ちから緩やかに劣化する傾向。

## 5. まとめ

このデータから、適切な学習データを用意できれば KP256 / HKP256 いずれのアーキテクチャでも
**5 B positions の学習で KP256(2019) baseline を明確に上回る** ことが確認できた
(KP256 で +100 Elo 以上、HKP256 で +340 Elo 以上)。
したがって 5 B 学習させても baseline に勝てない場合は、学習データ側に問題がある可能性が高い。
