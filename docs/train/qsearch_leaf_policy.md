# 学習局面は qsearch 末端を採用する方針

## 出典

- やねうら王と NNUE の解説 (山岡忠夫, 2022-06-24): <https://tadaoyamaoka.hatenablog.com/entry/2022/06/24/222305>

## 要旨

NNUE の学習データは、**qsearch (静止探索) を通した末端局面**を採用する。

- **理由**: 対局中に NNUE が評価するのは常に qsearch 末端の局面。学習局面をその分布に一致させないとテスト時と訓練時で評価対象が乖離する。
- **経験的根拠**: nodchip 氏の検証で qsearch を行わないと弱くなることが確認されている。
- **Stockfish との違い**: Stockfish は `--smart-fen-skipping` (駒を取る局面と王手局面を除外) で代替したが、将棋では qsearch 方式のほうが有効。

## gensfen の sfen / score 不整合

`gensfen` コマンド (`source/learn/learner.cpp`) は以下のように動作する:

```cpp
auto pv_value1 = search(pos, depth);   // 通常探索
...
pos.sfen_pack(psv.sfen);               // root 局面を保存
psv.score = evaluate_leaf(pos, pv1);   // PV leaf での評価値
```

- **sfen**: root 局面 (qsearch 前、駒取り途中や王手局面も混入)
- **score**: PV leaf (実質 qsearch 末端) の評価値

この不整合を解消するのが `shuffle_kifu` の `ApplyQSearch=true` オプション。

## パイプライン

```
gensfen (depth探索)
  → raw/*.bin (root局面 + PV leaf評価値)
    → shuffle_kifu (ApplyQSearch=true)
      → shuffled.bin (qsearch末端局面 + 評価値/勝敗反転済み)
        → train (学習)
```

## 実装: shuffle_kifu コマンド (V8.50)

tanuki-dr5 の `ShuffleKifu` を YaneuraOu V8.50 に移植済み。`gensfen` で生成した raw binpack を qsearch leaf に変換し、シャッフルする USI コマンド。

### ソースファイル (V8.50)

| ファイル | 役割 |
|---|---|
| `source/tanuki_kifu_shuffler.h` | `Tanuki::ShuffleKifu` 宣言 |
| `source/tanuki_kifu_shuffler.cpp` | 実装本体 |
| `source/tanuki_kifu_reader.h/.cpp` | binpack 読み込み |
| `source/tanuki_kifu_writer.h/.cpp` | binpack 書き出し |
| `source/tanuki_progress.h/.cpp` | 進行度推定 (フィルタ用) |
| `source/usi.cpp` (871行目) | `shuffle_kifu` コマンド登録 |
| `source/usi_option.cpp` (240行目) | USI オプション登録 |

### ApplyQSearch の処理フロー

1. raw binpack から 1M 件単位で `PackedSfenValue` を読み込む
2. `ApplyQSearch=true` の場合、OpenMP 並列で各レコードに対して:
   - `set_from_packed_sfen()` で局面を復元
   - `Learner::qsearch(pos)` を実行し PV を取得
   - PV を `do_move` で末端まで進める
   - `pos.sfen_pack(record.sfen)` で **leaf 局面** の sfen に置換
   - `record.move = MOVE_NONE` に設定
   - root と leaf の手番が異なる場合、`score` と `game_result` を反転
3. 256 個の tmp ファイルにランダム分配 (Pass 1)
4. 各 tmp を `std::shuffle` → 最終 `shuffled.bin` にマージ (Pass 2)

### USI オプション

| オプション名 | デフォルト | 説明 |
|---|---|---|
| `KifuDir` | `""` | 入力 binpack フォルダ |
| `ShuffledKifuDir` | `kifu_shuffled` | 出力フォルダ |
| `ShuffledMinPly` | 1 | 最小手数フィルタ |
| `ShuffledMaxPly` | INT_MAX/2 | 最大手数フィルタ |
| `ShuffledMinProgress` | `0.0` | 最小進行度フィルタ |
| `ShuffledMaxProgress` | `1.0` | 最大進行度フィルタ |
| `ApplyQSearch` | `false` | qsearch leaf 置換を行うか |

### 使用例

```
setoption name EvalDir value eval/hkp768
setoption name FV_SCALE value 40
setoption name Threads value 8
setoption name USI_Hash value 8192
setoption name KifuDir value data/run1/raw
setoption name ShuffledKifuDir value data/run1
setoption name ApplyQSearch value true
isready
shuffle_kifu
quit
```

### 注意事項

- `shuffle_kifu` は raw データの約 2 倍のディスク容量を一時的に使用する (256 個の中間ファイル)
- 進行度フィルタ (`ShuffledMinProgress`/`ShuffledMaxProgress`) を使う場合は `progress.bin` が必要
- binpack 1 レコード = 40 バイト (`PackedSfenValue` 構造体)

## tanuki-dr5 から V8.50 への移植で変更した点

### tanuki-dr5 固有機能の扱い

| 機能 | tanuki-dr5 | V8.50 | 備考 |
|---|---|---|---|
| `Tanuki::Progress` | あり | 移植済み | 進行度フィルタ用 |
| `record.last_position` | あり (手数リセットに使用) | 移植済み | フィールドは PackedSfenValue に存在 |
| `ShuffledMinPly`/`ShuffledMaxPly` | あり | 移植済み | |
| `ShuffledMinProgress`/`ShuffledMaxProgress` | あり | 移植済み | |
| Windows API (`_mkdir`, `_fseeki64` 等) | あり | POSIX 化済み | `mkdir`, `fseeko` 等に置換 |

### V8.50 側で統一済みのコンポーネント

gensfen / shuffle_kifu に影響する以下のコンポーネントは tanuki-dr5 と統一済み:

| コンポーネント | 変更内容 |
|---|---|
| TT API | `TTEntry*` + `bool& found` 方式に統一 (`tt.h`/`tt.cpp` 全面置換) |
| TT メモリ管理 | `LargeMemory` RAII (`memory.h` 追加) |
| VALUE_SUPERIOR | 31743 → 28000 |
| VALUE_MAX_EVAL | 31743 → 27000 |
| VALUE_KNOWN_WIN | 追加 (30744) |
| DEPTH_ENTRY_OFFSET | -3 → -7 |
| gensfen seed | 追加済み (両エンジン共通) |
| gensfen2019 write_minply | 1 → 16 |

これにより、**gensfen + shuffle_kifu のパイプラインは V8.50 単体で完結する**。tanuki- バイナリは不要。

## 解決済み事項 (tanuki-dr5 に合わせた判断)

### write_minply / write_maxply のフィルタ基準

**root 局面の ply を基準にする** (tanuki-dr5 と同一)。

gensfen 内の `ply < write_minply - 1` チェックは対局進行中のカウンタ (`ply`) に対して行われる。qsearch leaf への変換は shuffle_kifu の後処理なので、gensfen 時点では root 基準でフィルタするのが正しい。tanuki-dr5 も V8.50 も同じ実装。

### 千日手・王手局面の leaf 変換

**特別な処理は不要** (tanuki-dr5 と同一)。

gensfen 内で千日手は `pos.is_repetition()` で判定し、`REPETITION_WIN`/`REPETITION_DRAW`/`REPETITION_LOSE` でゲームを終了させる。千日手局面自体は書き出し対象にならない (`game_end = true` で対局が打ち切られ、それ以前の局面のみ `game_result` が付与される)。

shuffle_kifu の `ApplyQSearch` では `Learner::qsearch(pos)` を呼ぶだけであり、qsearch 内部で千日手局面に到達した場合は探索が自然に打ち切られるため、問題は起きない。

### smart-fen-skipping

**採用しない** (tanuki-dr5 と同一)。

tanuki-dr5 に `smart-fen-skipping` の実装はなく、将棋では qsearch leaf 方式で十分。Stockfish の `--smart-fen-skipping` は駒を取る局面と王手局面を除外するアプローチだが、`shuffle_kifu` の `ApplyQSearch` が同等以上の役割を果たしている。

### learner の shallow_value 取得方法の差異

tanuki-dr5 と V8.50 で learner (`learn` コマンド) の shallow_value 取得が異なる:

| | tanuki-dr5 | V8.50 |
|---|---|---|
| shallow_value | `Eval::evaluate(pos)` | `Learner::qsearch(pos)` |
| 前提 | shuffle_kifu で qsearch leaf 変換済み | 学習時に毎回 qsearch 実行 |

tanuki-dr5 は「shuffle_kifu で既に leaf に変換してあるから evaluate() だけで良い」という設計。V8.50 は「毎回 qsearch() を走らせて正確な値を取る」設計。`ApplyQSearch=true` で shuffle 済みデータを使う限り、どちらも同じ結果になる。現状は V8.50 の実装のままとする (qsearch の追加コストは learner 全体に対して微小)。
