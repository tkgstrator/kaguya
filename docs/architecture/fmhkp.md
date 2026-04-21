# FullMirrorHalfKP 特徴量 + 実装計画

## 概要

`FullMirrorHalfKP` は MirrorHalfKP ([mhkp.md](./mhkp.md)) をさらに推し進め、**K 側 (玉位置) と P 側 (盤上駒位置) の双方を 5 筋対称化**した特徴量。mhkp が K のみを 81→45 圧縮したのに対し、fmhkp は同じ `sym_file = min(file, 8-file)` を **P 側の盤上駒 1458 次元にも適用**し、盤上駒を 1458→810 に圧縮する。

### 動機
- mhkp は K 側対称化のみで HalfKP の ~56% (69660) に圧縮したが、**P 側にも同じ対称性が存在**する (左銀と右銀は局面全体を鏡映した際に入れ替わる、等)。
- 左右対称を P 側にも陽に織り込めば、同じ教師から抽出できる帰納バイアスがさらに強くなり、学習効率が上がる可能性がある。
- 目標次元: **40500** (mhkp の 58%、HalfKP の 32%)。WASM サイズでさらに有利。

## 設計

### 定義
玉 file と駒 file の両方に `sym_file = min(file, 8 - file)` を適用:

```
sym_file(f) = min(f, 8 - f)               // 0..4
king_index  = sym_file(sq_k) * 9 + rank_of(sq_k)   // 0..44
```

P 側 (盤上駒) は `piece_bonapiece` の再マップテーブル `piece_to_sym_bonapiece` を新設し、駒の盤上位置を `sym_file × 9 = 45` マスへ集約する。持ち駒 (`< fe_hand_end = 90`) は位置情報を持たないので**そのまま不変**。

```
fe_hand_end        = 90          // 持ち駒。位置なし、不変
piece_board_sym    = 1458 * 45 / 81 = 810   // 盤上駒を sym_file で圧縮
fe_end_sym         = fe_hand_end + piece_board_sym = 900
kDimensions        = 45 * fe_end_sym = 45 * 900 = 40500
```

| 量 | 値 |
|---|---|
| sym_file | 5 |
| rank | 9 |
| 玉位置解像度 | 45 |
| 盤上駒マス解像度 | 45 (= 5 × 9) |
| 持ち駒次元 (不変) | 90 |
| 盤上駒次元 (圧縮後) | 810 |
| fe_end_sym | 900 |
| **kDimensions** | **40500** |
| active 数 | 38 (`PIECE_NUMBER_KING`) |
| Refresh Trigger | `kFriendKingMoved` |

### MakeIndex ロジック
```
king_index = sym_file(sq_k) * 9 + rank_of(sq_k)        // 0..44
sym_p      = SymBonaPiece(p)                           // fe_end(1548) → fe_end_sym(900)
index      = king_index * fe_end_sym + sym_p           // 0..40499
```

`SymBonaPiece(p)`:
- `p < fe_hand_end (90)`: 持ち駒はそのまま返す (`p`)
- それ以外: `p - fe_hand_end` を (駒種インデックス, square) に分解、square を sym_file で圧縮した 45 マス表現に変換、`fe_hand_end + 駒種 × 45 + sym_sq` を返す

事前計算された `piece_to_sym_bonapiece` テーブル (サイズ `fe_end = 1548`) を通すのが実装上シンプル。

### MirrorHalfKP からの差分

| 観点 | MirrorHalfKP | **FullMirrorHalfKP** |
|---|---|---|
| K 側対称化 | ✓ (81→45) | ✓ (81→45) |
| P 側盤上駒対称化 | ✗ (1458 のまま) | **✓ (1458→810)** |
| P 側持ち駒 | 不変 (90) | 不変 (90) |
| ミラー適用条件 | 玉 file ≥ 5 のときのみ駒を `MirrorBonaPiece` | **常に `SymBonaPiece`** (駒側も左右対称表現で持つ) |
| fe_end | 1548 | **900** |
| kDimensions | 69660 | **40500** |

`MirrorHalfKP` は「玉 file < 5 なら駒そのまま、>= 5 ならミラー」の条件分岐で P 側は絶対座標を保持していた。`FullMirrorHalfKP` は P 側を最初から対称座標に押し込むので、玉位置によらず常に同じ変換を適用できる。

### HalfKP / MirrorHalfKP / FullMirrorHalfKP の次元比較

| Feature | K 解像度 | fe_end | 合計次元 | HalfKP 比 |
|---|---:|---:|---:|---:|
| HalfKP         | 81 | 1548 | 125,388 | 100% |
| MirrorHalfKP   | 45 | 1548 |  69,660 |  56% |
| **FullMirrorHalfKP** | 45 |  900 |  **40,500** |  **32%** |

### 期待される効果
- 左右対称を K と P の両面で陽に共有 → 教師データの「ミラー対称性による倍加」効果が mhkp より強い。
- パラメータ数は HalfKP の 1/3 まで減るので、WASM サイズは同 L1 なら大幅に軽くなる。
- L1=256 維持で表現力損失は少ないと見込むが、42% の次元削減がどの程度 Elo に響くかは実測必須。

### リスクと懸念
- 盤面は**厳密には左右非対称**。戦型・持ち駒投入方向・先手後手の向きなど、微妙な非対称性が存在する。P 側を強制対称化すると、これらの情報が学習時に見えなくなる。
- NNUE で K+P 両対称化の成功例は既知の範囲では少ない (AobaNNUE や dlshogi は K のみ対称)。経験則上の回避理由がある可能性あり。
- FT 入力次元は減るが、active 数 (38) は変わらないので forward pass のコストは FT 入力側の重み行列サイズ減にほぼ対応。学習速度向上は軽微の見込み。

## 実装タスク (Write order)

### C++ 側 (YaneuraOu)
1. `YaneuraOu/source/eval/nnue/features/full_mirror_half_kp.h` 新規
   - `kDimensions = 45 * 900 = 40500`
   - `kHashValue = 0x5D69D5BCu` (MirrorHalfKP の `0x5D69D5BA` の次)
   - `SymBonaPiece(BonaPiece p)` を静的に提供 (fe_hand_end 境界で分岐)
   - `Refresh Trigger = kFriendKingMoved`
2. `YaneuraOu/source/eval/nnue/features/full_mirror_half_kp.cpp` 新規
   - `piece_to_sym_bonapiece[fe_end]` テーブルを初回 access 時に構築
   - `AppendActiveIndices` / `AppendChangedIndices` を mirror_half_kp.cpp ベースで実装
3. `YaneuraOu/source/eval/nnue/architectures/full-mirror-half-kp_256x2-32-32.h` 新規 (L1=256 のみ)
4. `YaneuraOu/source/eval/nnue/nnue_architecture.h` に `EVAL_NNUE_FMHKP256` 分岐追加
5. `YaneuraOu/source/Makefile` に `YANEURAOU_ENGINE_NNUE_FMHKP256` edition + バイナリ名 `YaneuraOu-FMHK-P_256-32-32`
6. `CMakeLists.txt` の `YANEURAOU_SOURCES` に `full_mirror_half_kp.cpp` 追加

### Python 側 (nnue-pytorch)
7. `model/features/blocks.py` に `FullMirrorHalfKP` クラス追加
   - `NUM_FMHKP_KING_POSITIONS = 45`
   - `NUM_FMHKP_FE_END_SYM = 900`
   - `NUM_FMHKP_FEATURES = 45 * 900 = 40500`
   - `FMHKP_HASH = 0x5D69D5BC`
8. `get_feature_block_clss` リストに `FullMirrorHalfKP` 追加
9. `scripts/model_eval/ckpt_info.py` の `INPUT_DIM_TO_FEATURES` に `40500: "FullMirrorHalfKP"` と `ENGINE_MAP` に `("FullMirrorHalfKP", 256): "./engine/YaneuraOu-FMHK-P_256-32-32"` 追加
10. `scripts/train.py` の `MODEL_CONFIGS` に `"fmhkp256": {"features": "FullMirrorHalfKP", "l1": 256}`
11. `scripts/train/callbacks.py` の `ENGINE_MAP` に同上エントリ
12. `scripts/eval_model.py` / `scripts/eval_model.sh` の features リストに追加

### データローダ
13. `training_data_loader.cpp` に `FullMirrorHalfKP` struct を mhkp 準拠で追加
    - `sym_bonapiece()` 関数を実装 (C++ 側の `SymBonaPiece` と完全一致)
    - `fill_features_sparse` で `king_index * 900 + sym_p`
    - feature_set dispatch に `else if (feature_set == "FullMirrorHalfKP")` 分岐

### スキル / ドキュメント
14. `.claude/skills/model-eval/SKILL.md` の「有効な (feature, L1) 組み合わせ」表に `fmhkp` 行追加、glob pattern 表にも追加
15. `.claude/skills/model-train/models.md` に `fmhkp256` 行追加、Type 概説に `FMHKP` 項追加

## 検証計画

1. L1=256 のみ実装、mhkp256 と**完全同条件** (hao_depth9 / 100 epoch / 16384 mode) で学習
2. vs kp256_2019 で 1000 局対戦、Elo 計測
3. vs mhkp256_v1 (同 epoch 近辺の ckpt) でも 1000 局、直接対決で Elo 差を見る
4. 期待値:
   - 成功ケース: mhkp256 と同等 (±25 Elo 以内)、サイズは 58%
   - 失敗ケース: 表現力不足で -50〜-100 Elo 低下 → P 側対称化の経験則回避理由を裏付け

## 確定パラメータ (提案時点、要承認)

- **L1 = 256 のみ** 先行実装 (mhkp256 と比較できるよう条件固定)
- **Network = 256-32-32-1** (mhkp256 / kp256 / bhkp256 / hkp256 と同じトポロジ)
- Edition 名: `YANEURAOU_ENGINE_NNUE_FMHKP256`、バイナリ名: `YaneuraOu-FMHK-P_256-32-32`
- Python `-m fmhkp256`、feature prefix `fmhkp`
- Hash value: `0x5D69D5BC` (MirrorHalfKP の次、HalfKP の `0x5D69D5B8` と区別)

## 評価結果

### 評価条件 (共通)

- 対戦相手: `kp256_2019` (eval/kp256/nn.bin, FV_SCALE=20, 固定ベースライン) および `mhkp256_v1` (直接対決)
- 探索条件: byoyomi 500ms, threads 4, hash 1024 MB, concurrency 16
- 対局数: 1000 / 開始局面: data/balanced_ply32.sfen

### fmhkp256_v1 vs kp256_2019 (計画, 未実施)

| 項目 | 値 |
|---|---|
| challenger | `fmhkp256_v1` (予定、mhkp256_v1 と同条件で学習) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB |
| Elo 期待値 | +200 〜 +300 (mhkp256_v1_e65 の +286 近辺) |

### fmhkp256_v1 vs mhkp256_v1 (計画, 未実施 — 直接対決)

| 項目 | 値 |
|---|---|
| challenger | `fmhkp256_v1` (予定) |
| opponent   | `mhkp256_v1_e65` (epoch=65, step=1,602,000) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB |
| Elo 期待値 | ±25 以内なら成功 (P 側対称化の情報損失なし)、-50 未満は失敗 (経験則の回避理由を裏付け) |

**所見**: 学習未実施 (2026-04-20 時点、両方保留)。実施後に各カードを計測値で更新。

## 関連ファイル

- [`features/full_mirror_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — 本特徴量の実装
- [`features/mirror_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — mhkp (K のみ対称)、ベースにする
- [`features/half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — 最上位の HalfKP
- [kp.md](./kp.md), [hkp.md](./hkp.md), [bhkp.md](./bhkp.md), [mhkp.md](./mhkp.md) — 対比対象
