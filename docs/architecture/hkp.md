# HalfKP 特徴量

## 概要

HalfKP は Shogi NNUE の de-facto 標準。自玉 (または敵玉) の位置 `K` と、玉以外の駒 `P` を **joint index** として 1 特徴にまとめる。「この玉の配置のときにこの駒はここにある」というペアを 1 次元として学習できるため、KP よりも表現力が大きい。

実装: [`YaneuraOu/source/eval/nnue/features/half_kp.h`](../../YaneuraOu/source/eval/nnue/features/half_kp.h)

"Half" は 2 perspective (Friend / Enemy) それぞれで **自分の玉を基準にした半分の表現** を作り、FT の 2 perspective 入力に食わせることから来ている。

## 次元数

```
kDimensions = SQ_NB × fe_end = 81 × 1548 = 125388
```

| 量 | 値 |
|---|---|
| 玉の位置 | 81 (9 × 9) |
| BonaPiece 範囲 | 1548 (`fe_end`, 盤上駒 + 持ち駒) |
| HalfKP 全次元 | **125388** (Friend 側のみ、Enemy 側も同じ次元を別の FT で持つ) |
| 同時 active 数 | 38 (`PIECE_NUMBER_KING`) |

KP (1710) に対して **~73 倍の次元数**。ただし active 数は 38 個のまま、スパース度は高い。

## FT Refresh Trigger

- `Side::kFriend` → `kFriendKingMoved` (自玉が動いたら全 active index が変わる → FT 全計算)
- `Side::kEnemy` → `kEnemyKingMoved`

つまり玉が動くたび FT の accumulator を全面再構築する。手番側だけ動かすなら OK だが、双方の玉が頻繁に動く王手ラッシュで多少重い。

## ネットワーク構造

### hao 系 (HalfKP 256x2-32-32)
[`architectures/halfkp_256x2-32-32.h`](../../YaneuraOu/source/eval/nnue/architectures/halfkp_256x2-32-32.h):

```
RawFeatures = FeatureSet<HalfKP<Side::kFriend>>
L1 = 256, Hidden = 32 → 32 → 1
```

`eval/hkp256/nn.bin` は hao (習甦系) 互換、FV_SCALE = 20。

### AobaNNUE 系 (HalfKP 768x2-16-64)
[`architectures/halfkp_768x2-16-64.h`](../../YaneuraOu/source/eval/nnue/architectures/halfkp_768x2-16-64.h):

```
L1 = 768, Hidden = 16 → 64 → 1
```

`eval/hkp768/nn.bin` は AobaNNUE 互換、FV_SCALE = 40。Hidden の第 1 層が 16 と狭く、第 2 層が 64 と広い逆台形構造。

## 特性

### 強み
- **玉と駒の joint を陽にモデル化**。矢倉の壁、穴熊の金銀、美濃の金、すべて 1 インデックスで表現できる。
- このため同 L1 で KP より明確に強い。実測 +342 Elo (HKP256 ピーク時) は KP256 ピーク (+182 Elo / 44.73B pos) を大きく上回る。
- Shogi の pro-human 棋力到達は HalfKP 系列で実現された歴史があり、教師データ・ハイパラ知見も豊富。

### 弱み
- **パラメータ数 = 125388 × L1 × 2 perspective**。L1=256 で ~64M parameter、L1=768 で ~192M parameter。
  - FT 1 本で KP の ~73 倍重い → WASM / モバイル向けではメモリ帯域と転送サイズが厳しい。
- **左右対称性を陽に使わない**。file=0 の玉と file=8 の玉に独立した重みを割り当てるため、対称な局面の学習が 2 倍必要。
  - この冗長を潰す改良が MirrorBucketHalfKP / (新規) MirrorHalfKP ([bhkp.md](./bhkp.md) 参照)。
- 玉を動かすと FT refresh が走る → 探索末端の計算コストがやや高い。

## 評価結果

### 評価条件 (共通)

- 対戦相手: `kp256_2019` (eval/kp256/nn.bin, FV_SCALE=20, 固定ベースライン)
- 探索条件: byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32
- 対局数: 1000 / 開始局面: data/balanced_ply32.sfen
- 実測データは [`docs/evaluation_trained_model.md` 4.1 節](../evaluation_trained_model.md) 参照

### hkp256_s312k vs kp256_2019 (1000 局, 5 B pos 到達)

| 項目 | 値 |
|---|---|
| challenger | `hkp256` (step=312,000, 5.11 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+875 / -120 / =5** (勝率 87.5%) |
| Elo       | **+342.04 ± 32.65** (95% CI) |

### hkp256_s624k vs kp256_2019 (1000 局, ピーク)

| 項目 | 値 |
|---|---|
| challenger | `hkp256` (step=624,000, 10.22 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+905 / -88 / =7** (勝率 90.5%) |
| Elo       | **+398.76 ± 36.95** (95% CI) |

### hkp256_s1254k vs kp256_2019 (1000 局, ピーク後)

| 項目 | 値 |
|---|---|
| challenger | `hkp256` (step=1,254,000, 20.55 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32 |
| W / L / D | **+901 / -96 / =3** (勝率 90.1%) |
| Elo       | **+386.58 ± 36.14** (95% CI) |

### hkp768 vs kp256_2019 (参考値, AobaNNUE 互換)

| 項目 | 値 |
|---|---|
| challenger | `hkp768` (約 45 B pos 学習, FV_SCALE=40) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 未計測 (1000 局換算) |
| Elo       | ≈ **+400** (参考値、W/L/D 未記録) |

**所見**: 5 B pos 時点で +342 Elo 到達、10 B pos 付近でピーク +398 Elo、以降は頭打ち〜軽微な劣化。KP256 ピーク (+182) を大きく上回り HalfKP の joint 表現力の有効性を実証。HKP768 (AobaNNUE 互換) は ~45 B pos 学習で ≈ +400 Elo、現行最強格。ただし WASM では転送量と FT メモリがボトルネックになるため、KP 路線でここに追い付くのが本プロジェクトのゴール。

## 関連ファイル

- [`features/half_kp.cpp`](../../YaneuraOu/source/eval/nnue/features/half_kp.cpp) — `AppendActiveIndices` / `AppendChangedIndices` / `MakeIndex` の実装
- [`features/half_kp_vm.h`](../../YaneuraOu/source/eval/nnue/features/half_kp_vm.h) — VM (仮想玉位置, vertical mirror?) 拡張 (未使用)
- `model/features/half_kp.py` — Python 側の特徴量定義
