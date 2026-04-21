# 学習局面は qsearch 末端を採用する方針

## 出典

- やねうら王と NNUE の解説 (山岡忠夫, 2022-06-24): <https://tadaoyamaoka.hatenablog.com/entry/2022/06/24/222305>

## 要旨

NNUE の学習データは、**qsearch (静止探索) を通した末端局面**を採用する。

- **理由**: 対局中に NNUE が評価するのは常に qsearch 末端の局面。学習局面をその分布に一致させないとテスト時と訓練時で評価対象が乖離する。
- **経験的根拠**: nodchip 氏の検証で qsearch を行わないと弱くなることが確認されている。
- **Stockfish との違い**: Stockfish は `--smart-fen-skipping` (駒を取る局面と王手局面を除外) で代替したが、将棋では qsearch 方式のほうが有効。

## 現状のパイプラインとの差分

`YaneuraOu/source/learn/learner.cpp` の `gensfen` コマンドは、

```cpp
auto pv_value1 = search(pos, depth);   // 通常探索
...
pos.sfen_pack(psv.sfen);               // root 局面を保存
psv.score = evaluate_leaf(pos, pv1);   // PV leaf での評価値
```

となっており、

- **sfen**: root 局面 (qsearch 前、駒取り途中や王手局面も混入)
- **score**: PV leaf (実質 qsearch 末端) の評価値

という不整合がある。`training_data_loader.cpp` 側では qsearch を一切行わず binpack をそのまま読むため、この不整合はそのまま学習に持ち込まれている。

## 今後の方針

1. **新規教師の生成では qsearch 末端を保存する**
   - gensfen 側で `pos.sfen_pack` を PV leaf (qsearch 終了時の局面) まで進めた位置で行う。
   - `psv.move` / `psv.game_result` も leaf を起点に整合させる。
2. **既存 binpack は基本的に再利用しない**
   - 出自 (gensfen / rescore / 外部提供) が混在しているので、qsearch 末端に変換するより、新規生成に切り替えるほうがクリーン。
   - どうしても再利用したい場合のみ、別途「binpack を qsearch で leaf に置換する」変換スクリプトを作る (rescore の亜種)。
3. **nnue-pytorch 側で qsearch は実装しない**
   - Python/C++ どちらで書いても Position/TT を扱う必要があり重い。C++ の `learner.cpp` (nodchip 実装) と役割分担を崩さない。

## 実装: shuffle_kifu コマンド

tanuki-dr4-learner の `ShuffleKifu` を YaneuraOu 7.62 に移植。既存 binpack を qsearch leaf に変換する USI コマンド。

### ソースファイル

- `YaneuraOu/source/learn/kifu_shuffler.h` — 名前空間 `KifuShuffler` の宣言
- `YaneuraOu/source/learn/kifu_shuffler.cpp` — 実装本体

### 動作

1. `KifuDir` フォルダ内の全 `.bin` を 1M 件単位で読み込む
2. `ApplyQSearch=true` の場合、各 record に対して OpenMP 並列で `Learner::qsearch(pos)` を実行し、PV 末端まで `do_move` → `sfen_pack` で sfen を leaf に置換。`move=MOVE_NONE`、手番が異なれば `score`/`game_result` を反転
3. 256 個の tmp ファイルにランダム分配 (Pass 1)
4. 各 tmp を `std::shuffle` → 最終 `ShuffledKifuDir/shuffled.bin` にマージ (Pass 2)

### USI オプション

| オプション名          | デフォルト     | 説明                          |
|-----------------------|----------------|-------------------------------|
| `KifuDir`             | `kifu`         | 入力 binpack フォルダ         |
| `ShuffledKifuDir`     | `kifu_shuffled`| 出力フォルダ                  |
| `ApplyQSearch`        | `false`        | qsearch leaf 化を行うか       |
| `KifuReaderBufferSize`| 1048576        | 読み込みバッファ (bytes)      |
| `KifuWriterBufferSize`| 1048576        | 書き込みバッファ (bytes)      |

### ビルドコマンド

```sh
# halfkp_768 (AobaNNUE 互換)
make evallearn YANEURAOU_EDITION=YANEURAOU_ENGINE_NNUE_HALFKP_768X2_16_64 \
  COMPILER=g++ TARGET_CPU=AVX2 -j$(nproc)
# バイナリ: YaneuraOu/source/YaneuraOu-by-gcc

# halfkp_256 (標準 NNUE)
make evallearn YANEURAOU_EDITION=YANEURAOU_ENGINE_NNUE \
  COMPILER=g++ TARGET_CPU=AVX2 -j$(nproc)
```

### 使用例

```
setoption name EvalDir value eval/hkp768
setoption name FV_SCALE value 40
setoption name KifuDir value data/aobannue_depth9
setoption name ShuffledKifuDir value data/aobannue_depth9_shuffled
setoption name ApplyQSearch value true
isready
shuffle_kifu
```

### 剥がした tanuki 固有機能

- `Tanuki::Progress` 依存 (`ShuffledMinProgress` / `ShuffledMaxProgress` フィルタ) — 削除
- `record.last_position` / `ShuffledMinPly` / `ShuffledMaxPly` フィルタ — 削除
- Windows 専用 API (`_mkdir`, `_fseeki64` 等) — POSIX 版に統一

## 未決事項

- gensfen 改造時、`write_minply` / `write_maxply` のフィルタは root を基準にするか leaf を基準にするか。
- 千日手・王手局面を leaf にすると問題がないか (現状の evaluate_leaf は千日手で早期 return しているが、sfen 側も同じ扱いでよいか)。
- Stockfish 互換の `smart-fen-skipping` を併用するかどうか。
