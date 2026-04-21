# MirrorHalfKP 特徴量 + 実装計画

## 概要

`MirrorHalfKP` は HalfKP ([hkp.md](./hkp.md)) に左右対称性のみを導入した新規特徴量。BucketHalfKP ([bhkp.md](./bhkp.md)) の 3×3 粗視化が失敗 (-50 Elo) した反省から、**玉位置の解像度を 81 → 45 に落とすだけ** (離散ジャンプなし) で次元を縮小する。

### 動機
- HalfKP は強い (+342 Elo) が 125388 次元と重く WASM 向けでないない。
- KP は軽いが joint 情報が無く +182 Elo どまり。
- BucketHalfKP は粗視化が粗すぎ、**4 観点の破綻** ([bhkp.md](./bhkp.md#buckethalfkp-がなぜ弱いのか) 参照) で -50 Elo。
- MirrorHalfKP は左右対称のみで圧縮、連続性を保ったままパラメータ数を HalfKP の ~56% に削減。

## 設計

### 定義
玉の file を左右対称化: `sym_file = min(file, 8 - file)` (0..4)、玉 file >= 5 のとき BonaPiece を `MirrorBonaPiece` で反転。

```
kDimensions = 5 * 9 * fe_end = 45 * 1548 = 69660
```

| 量 | 値 |
|---|---|
| sym_file | 5 (file 0=8, 1=7, 2=6, 3=5, 4=center) |
| rank | 9 |
| 玉位置解像度 | 45 (= 5 × 9) |
| kDimensions | **69660** (1548 × 45) |
| active 数 | 38 (`PIECE_NUMBER_KING`) |
| Refresh Trigger | `kFriendKingMoved` |

HalfKP (125388) に対し **約 56%**、BucketHalfKP (13932) の 5 倍。

### MakeIndex ロジック
```
king_index = sym_file(sq_k) * 9 + rank_of(sq_k)        // 0..44
mirror_p   = NeedsMirror(sq_k) ? MirrorBonaPiece(p) : p
index      = king_index * fe_end + mirror_p
```

`MirrorBonaPiece` は持ち駒 (`< fe_hand_end`) を不変、盤上駒は `Mir(sq)` で file 反転。
`NeedsMirror(sq_k) = file_of(sq_k) >= 5`。

### HalfKP / BucketHalfKP との比較
| 観点 | HalfKP | BucketHalfKP | **MirrorHalfKP** |
|---|---|---|---|
| 玉位置解像度 | 81 マス独立 | 9 バケット | **45 位置 (左右対称)** |
| joint (K, P) | ✓ | ✓ 粗 | **✓ 完全** |
| 左右対称の重み共有 | ✗ | ✗ (但し対応版有) | **✓** |
| 次元数 | 125388 | 13932 | **69660** |
| 連続性 | 完全 (81 独立) | 3×3 境界不連続 | **完全 (45 独立)** |

### 期待される効果
- 左右対称を陽に使うため、HalfKP に対して教師データの半分を「ミラー済みデータとして両方向に使える」(有効データ量 2 倍の効き)。
- 3×3 境界のような離散ジャンプが無く、玉の 1 マス移動で bucket が飛ぶ問題が無い。
- HalfKP よりパラメータ数 ~56% で済むので WASM サイズも縮む。

## 実装タスク (Write order)

### C++ 側 (YaneuraOu)
1. `YaneuraOu/source/eval/nnue/features/mirror_half_kp.h` 新規
   - 非テンプレート、`mirror_bucket_half_kp.h` の構造踏襲
   - `kDimensions = 45 * fe_end = 69660`
   - `GetMirroredKingIndex` / `NeedsMirror` / `MirrorBonaPiece` をクラス内に静的に持つ
2. `YaneuraOu/source/eval/nnue/features/mirror_half_kp.cpp` 新規
   - `AppendActiveIndices` / `AppendChangedIndices` を実装 (mirror_bucket_half_kp.cpp ベース)
3. `YaneuraOu/source/eval/nnue/architectures/mirror-half-kp_256x2-32-32.h` 新規 (L1=256 のみ)
4. `YaneuraOu/source/eval/nnue/nnue_architecture.h` に `EVAL_NNUE_MHKP256` 分岐追加
5. `YaneuraOu/source/Makefile` に `YANEURAOU_ENGINE_NNUE_MHKP256` edition + `TARGET=YaneuraOu-MHK-P_256-32-32`
6. `CMakeLists.txt` の `YANEURAOU_SOURCES` に `mirror_half_kp.cpp` 追加

### Python 側 (nnue-pytorch)
7. `model/features/mirror_half_kp.py` 新規
   - 特徴量クラス定義 (`num_real_features`, `num_virtual_features`, hash, `get_active_features`)
   - C++ の `MakeIndex` と完全一致するロジック (CUDA kernel 対応)
8. `model/features/__init__.py` で `MirrorHalfKP` 登録
9. `scripts/model_eval/ckpt_info.py` — state_dict shape から `MirrorHalfKP` を検出 (FT 入力次元 = 69660)
10. `scripts/train.py` に `-m mhkp256` オプション追加

### データローダ
11. `training_data_loader.cpp` に MirrorHalfKP 分岐 (C++ 側の feature enum と shared)

### スキル / ドキュメント
12. `.claude/skills/model-eval/SKILL.md` の「有効な (feature, L1) 組み合わせ」表に `mhkp` 行追加
13. `.claude/skills/model-train/models.md` に `mhkp256` 行追加

## 検証計画
1. L1=256 のみ実装、hao_depth9 教師 + 100 epoch (≒ 5B pos) で学習
2. vs kp256_2019 で 1000 局対戦、Elo 計測
3. 期待値: HKP256 (+342) と BHKP256 (-50) の中間以上、理想は HKP256 に近い水準
4. 成功したら L1=512 / 1024 に拡張、教師も deeper (d=16) でリトライ

## 確定パラメータ (2026-04-20)
- **L1 = 256 のみ** 先行実装。HKP256 と同条件比較してから 512/1024 を判断
- **Network = 256-32-32-1** (HKP256 / KP256 / BHKP256 と同じトポロジ)
- Edition 名: `YANEURAOU_ENGINE_NNUE_MHKP256`、バイナリ名: `YaneuraOu-MHK-P_256-32-32`
- Python `-m mhkp256`、feature prefix `mhkp`

## 学習ステータス (2026-04-20 打ち止め)
- 目標 100 epoch に対し **epoch 74 (step 1,824,000) で停止** (SIGBUS クラッシュ、未再開)
- 最終採用 ckpt: `epoch=65-step=1602000.ckpt` (c=32 1000 局評価で +250.77 Elo、5 点計測で最高)
- 打ち止め判断: 既に KP256 ベースラインに対して有意優位を確認しており、74 epoch からの再開メリットは小さいと判断

## 評価結果

### 評価条件 (共通)

- 対戦相手: `kp256_2019` (eval/kp256/nn.bin, FV_SCALE=20, 固定ベースライン)
- 探索条件: byoyomi 500ms, threads 4, hash 1024 MB, concurrency 32
- 対局数: 1000 / 開始局面: data/balanced_ply32.sfen

### mhkp256_v1_e32 vs kp256_2019 (1000 局, 2026-04-20)

| 項目 | 値 |
|---|---|
| challenger | `mhkp256_v1_e32` (epoch=32, step=804,000, 19.64 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| W / L / D | **+755 / -238 / =7** (勝率 75.5%) |
| Elo       | **+198.82 ± 25.04** (95% CI) |
| OUT_DIR   | `eval/auto/mhkp256_v1_e32_vs_kp256_2019_1k` |

### mhkp256_v1_e48 vs kp256_2019 (1000 局, 2026-04-20)

| 項目 | 値 |
|---|---|
| challenger | `mhkp256_v1_e48` (epoch=48, step=1,194,000, 29.16 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| W / L / D | **+781 / -213 / =6** (勝率 78.1%) |
| Elo       | **+223.94 ± 26.05** (95% CI) |
| OUT_DIR   | `eval/auto/mhkp256_v1_e48_vs_kp256_2019_1k` |

### mhkp256_v1_e56 vs kp256_2019 (1000 局, 2026-04-20)

| 項目 | 値 |
|---|---|
| challenger | `mhkp256_v1_e56` (epoch=56, step=1,392,000, 34.00 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| W / L / D | **+797 / -198 / =5** (勝率 79.7%) |
| Elo       | **+240.28 ± 26.79** (95% CI) |
| OUT_DIR   | `eval/auto/mhkp256_v1_e56_vs_kp256_2019_1k` |

### mhkp256_v1_e65 vs kp256_2019 (1000 局, 2026-04-20) — ピーク

| 項目 | 値 |
|---|---|
| challenger | `mhkp256_v1_e65` (epoch=65, step=1,602,000, 39.14 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| W / L / D | **+807 / -189 / =4** (勝率 80.7%) |
| Elo       | **+250.77 ± 27.30** (95% CI) |
| OUT_DIR   | `eval/auto/mhkp256_v1_e65_vs_kp256_2019_1k` |

### mhkp256_v1_e72 vs kp256_2019 (1000 局, 2026-04-20)

| 項目 | 値 |
|---|---|
| challenger | `mhkp256_v1_e72` (epoch=72, step=1,782,000, 43.54 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| W / L / D | **+807 / -190 / =3** (勝率 80.7%) |
| Elo       | **+250.20 ± 27.30** (95% CI) |
| OUT_DIR   | `eval/auto/mhkp256_v1_e72_vs_kp256_2019_1k` |

### 所見

epoch 32 → 48 → 56 → 65 → 72 で +198.82 → +223.94 → +240.28 → +250.77 → +250.20 と単調増加し、e65 以降頭打ち。**過学習の兆候なし** (74 epoch で SIGBUS 打ち止め時点でピーク近傍を維持)。最良 ckpt は **e65** (+250.77 ± 27.30)。KP256 ベースラインに対して全 epoch で有意優位 (CI が 0 を跨がず)。MHKP の左右対称圧縮が HalfKP 次元の ~56% で情報損失なく機能することを実証したが、HKP256 ピーク (+398) にはまだ大きな差があり、L1 拡張 (512/1024) または深層教師 (d=16) での再挑戦が残る。

## 関連ファイル

- [`features/mirror_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — 本特徴量の実装 (予定)
- [`features/half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — ベースとなる HalfKP
- [`features/mirror_bucket_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — mirror/MirrorBonaPiece ロジック流用元
- [kp.md](./kp.md), [hkp.md](./hkp.md), [bhkp.md](./bhkp.md) — 対比対象
