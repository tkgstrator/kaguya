# KP 特徴量

## 概要

KP は NNUE の最軽量な特徴量設計。玉の位置 `K` と、玉以外の駒 `P` を **互いに独立な 2 系統** としてfeature transformer (FT) に入れる。HalfKP のように玉と駒を結合してインデックス化しないため、次元数が桁違いに小さい。

実装: [`YaneuraOu/source/eval/nnue/features/k.h`](../../YaneuraOu/source/eval/nnue/features/k.h), [`p.h`](../../YaneuraOu/source/eval/nnue/features/p.h)

## 次元数

| 特徴量 | 値 | 根拠 |
|---|---|---|
| K | 162 | `SQ_NB * 2` = 81 × 2 (自玉 + 敵玉) |
| P | 1548 | `fe_end` (盤上駒 + 持ち駒の BonaPiece 範囲) |
| 合計 | **1710** | K + P の concat |

同時 active 数:
- K: 2 (自玉 + 敵玉)
- P: 38 (`PIECE_NUMBER_KING`, 玉以外の 38 駒)

つまり入力ベクトルは 1710 次元のうち **40 bit だけ立つスパース表現**。

## ネットワーク構造

WASM 主線で採用する純 KP の構成 ([`architectures/k-p_256x2-32-32.h`](../../YaneuraOu/source/eval/nnue/architectures/k-p_256x2-32-32.h)):

```
input(1710 sparse)
  → FT: 1710 × 256 × 2perspective  = FT out 512次元
  → Affine(512 → 32) → ClippedReLU
  → Affine(32 → 32)  → ClippedReLU
  → Affine(32 → 1)   → eval value
```

`256x2` は **L1=256 を 2 perspective (手番側 / 相手側) 分の 256 次元ずつ concat** して 512 次元という意味で、後段の Affine 32 層ではない点に注意。

L1 バリエーション:
- `k-p_256x2-32-32` (WASM 主線, 2019 KP256 互換)
- `k-p_512x2-32-32`
- `k-p_1024x2-32-32`

いずれも Hidden は 32 → 32 固定。L1 だけスケールする。

## 特性

### 強み
- **次元が極端に小さい** (1710) → FT の重みメモリが HalfKP (125388) の ~73 倍軽い。WASM / モバイル向け。
- 玉を動かしても P 側は影響を受けない → 差分計算の refresh 範囲が K のみ (`TriggerEvent::kNone`)。
- 学習データ少なめでも収束しやすい (パラメータ数が少ない)。

### 弱み
- 玉の位置と駒の位置の**joint 関係がモデル化されない**。
  - 例: 「自玉 8g + 歩 7f (矢倉の壁)」が 1 つの特徴として表現できない。玉の位置による駒の価値変動を FT が暗黙に学ぶ必要がある。
- このため HalfKP 系より Elo が低くなりがち。ただし L1 を大きくすれば (512/1024) 差は縮まる。

### 2019 KP256 基準
WASM やねうら王 2019 版のベースライン。本リポジトリでは `eval/kp256/nn.bin` として固定、新モデルの実用判定は対 kp256_2019 の 1000 局対戦で行う ([`feedback_kp256_baseline`](../../..//home/vscode/.claude/projects/-home-vscode-app/memory/feedback_kp256_baseline.md) 参照)。

## 評価結果

### 評価条件 (共通)

- 対戦相手: `kp256_2019` (eval/kp256/nn.bin, FV_SCALE=20, 固定ベースライン)
- 探索条件: byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32
- 対局数: 1000 / 開始局面: data/balanced_ply32.sfen
- 実測データ全量 (11 step 分) は [`docs/evaluation_trained_model.md` 4.2 節](../evaluation_trained_model.md) 参照

### kp256_s318k vs kp256_2019 (1000 局, 初期段階)

| 項目 | 値 |
|---|---|
| challenger | `kp256` (step=318,000, 5.21 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+648 / -344 / =8** (勝率 64.8%) |
| Elo       | **+109.07 ± 22.50** (95% CI) |

### kp256_s2730k vs kp256_2019 (1000 局, ピーク)

| 項目 | 値 |
|---|---|
| challenger | `kp256` (step=2,730,000, 44.73 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+738 / -257 / =5** (勝率 73.8%) |
| Elo       | **+182.16 ± 24.48** (95% CI) |

### kp256_s2916k vs kp256_2019 (1000 局, 劣化後)

| 項目 | 値 |
|---|---|
| challenger | `kp256` (step=2,916,000, 47.78 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+701 / -295 / =4** (勝率 70.1%) |
| Elo       | **+149.68 ± 23.51** (95% CI) |

**所見**: ~45 B pos でピーク +182 Elo、以降は過学習 or 教師限界で緩やかに劣化。同じ kp256 でも epoch 早打ちと epoch ピークで +70 Elo 以上差が出るため評価タイミング重要。HKP256 (+398 ピーク) / AobaNNUE (+400 前後) とは依然として差があるが、+182 は WASM 向け軽量モデルとして実用レベル、joint 情報なしでここまで伸びる点は特筆すべき。
