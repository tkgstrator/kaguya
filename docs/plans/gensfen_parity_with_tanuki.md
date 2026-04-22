# YaneuraOu V8.50 を tanuki-dr5 互換に改修するプラン

## 背景

`vendor/tanuki-` を `tanuki-dr5_production-learner` ブランチで取り込み、`vendor/YaneuraOu` の `learn` ブランチに `source/learn` 周り + `tanuki_progress` / `tanuki_kifu_{reader,writer,shuffler}` を移植済み。

**比較対象のコマンド**: 両エンジンが共通で持つ depth ベースの `gensfen` と `shuffle_kifu` (ApplyQSearch=true)。`gensfen2019` (nodes_limit ベース) も両エンジンに存在するが、主に depth ベースで比較を実施。

## 環境

| 要素 | 値 |
|---|---|
| OS | Ubuntu 24.04 (Noble) / devcontainer |
| g++ | 13.3.0 |
| clang++ | なし (g++ にフォールバック済) |
| OpenMP | libgomp1 |
| OpenBLAS | NONE (不要) |

## エンジンバイナリ

| エンジン | バイナリ | バージョン | 状態 |
|---|---|---|---|
| YaneuraOu V8.50 (HKP256) | `engines/YaneuraOu-HalfKP_256x2-32-32_learn` | 8.50git | ビルド済 |
| tanuki-dr5 (HKP256) | `engines/AobaNNUE-HalfKP_256x2-32-32_learn` | 5.33 | ビルド済 |

## Book の利用方法

エンジンのデフォルトは `BookDir=book`, `BookFile=standard_book.db` (上流のまま変更しない)。
`engines/book/user_book1.db` を使う場合は USI オプションで指定する:

```
setoption name BookDir value engines/book
setoption name BookFile value user_book1.db
```

---

## フェーズと進捗

### Phase 0 — 開発環境の構築

- [x] devcontainer (Ubuntu 24.04 / g++ 13.3) セットアップ
- [x] `build_yaneuraou.sh` に clang++ → g++ 自動フォールバック追加
- [x] V8.50 evallearn ビルド通過 (全バリアント: kp256, hkp256, hkp512, hkp768, hkp1024, hkp1024_64)
- [x] HKP768 アーキテクチャヘッダを V8.50 に追加 (`nnue_arch_gen.py` で生成)

### Phase 1 — V8.50 の gensfen クラッシュ修正

- [x] 症状の再現: `AsyncPRNG::seed` 表示直後に SIGSEGV / `free(): invalid pointer`
- [x] 原因特定: `MultiThink::go_think()` → `is_ready(true)` → `Threads.set()` → TT large-page メモリ破壊
- [x] 修正 1: `is_ready(true)` をコメントアウト (初回 isready で初期化済み)
- [x] 修正 2: `Options` 全体の復元を `BookOnTheFly` のみの復元に変更
- [x] gensfen 完走確認 (100 positions, Threads=1)
- [x] quit 時の SIGSEGV 修正 (初期実装: `release()` → Phase 5 で LargeMemory RAII に置換)

**変更ファイル (V8.50):**

| ファイル | 変更内容 |
|---|---|
| `source/learn/multi_think.cpp` | `is_ready(true)` をコメントアウト、Options 復元を BookOnTheFly のみに限定 |

### Phase 2 — tanuki-dr5 の Linux ビルド

- [x] Windows 依存コードの修正
- [x] HKP256 での evallearn ビルド通過 (エンジン ID: YaneuraOu NNUE 5.33)
- [x] HKP768 エディション追加
- [x] tanuki- バイナリで gensfen (depth ベース) が完走することを確認

**変更ファイル (tanuki-):**

| ファイル | 変更内容 |
|---|---|
| 複数ファイル | `_mkdir` → `mkdir`, `_MAX_PATH` → `PATH_MAX`, `_fseeki64` → `fseeko`, `_ftelli64` → `ftello` |
| `source/eval/nnue/nnue_architecture.h` | HKP768 エディション追加 |

### Phase 3 — seed パラメータの追加と gensfen 比較

- [x] 出力比較スクリプト (`scripts/compare_gensfen.py`) の作成
- [x] seed 固定機能の追加 (両エンジン)
- [x] seed 固定での決定性確認: 同一エンジン・同一 seed → MD5 完全一致
- [x] 統計分布比較 (TT 統一前, 1000 レコード): score mean diff 80, std diff 773, gamePly diff 7.22

**変更ファイル (V8.50 & tanuki- 共通):**

| ファイル | 変更内容 |
|---|---|
| `source/misc.h` | `AsyncPRNG::set_seed(u64)` メソッド追加 |
| `source/learn/multi_think.h` | `MultiThink::set_prng_seed(u64)` メソッド追加 |
| `source/learn/learner.cpp` | `MultiThinkGenSfen` の seed 表示をコンストラクタから `init()` に移動。gensfen コマンドに `seed` パラメータ追加、`set_prng_seed()` 呼び出し |

### Phase 4 — shuffle_kifu の動作確認

- [x] V8.50 で shuffle_kifu (ApplyQSearch=true) が完走することを確認
- [ ] tanuki- で shuffle_kifu が完走することを確認
- [ ] shuffled.bin のレコード数が元データと一致することを確認
- [ ] ApplyQSearch 適用後の score 分布を比較

### Phase 5 — TT 実装の統一 (V8.50 → tanuki- 互換)

- [x] V8.50 の tt.h/tt.cpp を tanuki-dr5 互換 API に全面置換
- [x] `LargeMemory` RAII クラスを memory.h に追加
- [x] thread.cpp から per-thread TT の `release()` 呼び出しを削除
- [x] yaneuraou-search.cpp の全 probe/save 呼び出し (約 70 箇所) を新 API に変換
- [x] types.cpp / unit_test.cpp の TT 参照を更新
- [x] HKP256 / HKP768 の両バリアントでクリーンビルド確認
- [x] gensfen + shuffle_kifu の動作確認
- [x] TT 統一後の統計比較: score std diff 773→552, gamePly diff 7.22→0.99 に改善

**変更ファイル (V8.50):**

| ファイル | 変更内容 |
|---|---|
| `source/tt.h` | 全面書き換え: `TTData`/`TTWriter`/tuple probe 廃止 → `TTEntry*`+`bool& found`。TTEntry フィールド順を tanuki- と同一に (key16, move16, value16, eval16, genBound8, depth8)。`release()` 削除。TranspositionTable に `LargeMemory tt_memory` メンバ追加 |
| `source/tt.cpp` | 全面書き換え: `save()` から generation8 引数削除 (TT.generation8 を直接参照)。PV ボーナス (`+2*pv`) と `relative_age()` 上書き条件を除去。probe() の置換エントリー選択をインライン式 `depth8 - ((263+gen-genBound8)&0xF8)` に変更。`resize()` を `tt_memory.alloc()` に変更 |
| `source/memory.h` | `LargeMemory` 構造体を追加 (`aligned_large_pages_alloc/free` の RAII ラッパー) |
| `source/thread.cpp` | `#if defined(EVAL_LEARN)` ブロック内の per-thread TT `release()` 呼び出しを削除 (LargeMemory の RAII で不要に) |
| `source/engine/yaneuraou-engine/yaneuraou-search.cpp` | 全 `auto [ttHit, ttData, ttWriter] = TT.probe(key, pos)` を `bool ttHit; TTEntry* tte = TT.probe(key, ttHit)` に変換。`ttData.move` → `pos.to_move(tte->move())`、`ttData.value` → `tte->value()` 等のアクセサ変換。`ttWriter.write(..., TT.generation())` → `tte->save(...)` (generation8 引数削除)。計約 70 箇所 |
| `source/types.cpp` | ponder 用 `tt.probe()` 呼び出しを新 API に変換 |
| `source/testcmd/unit_test.cpp` | `TranspositionTable::UnitTest` の呼び出しを無効化 (tanuki- 互換 TT には UnitTest なし) |

### Phase 5b — 定数の統一 (V8.50 → tanuki- 互換)

- [x] `VALUE_SUPERIOR`: `VALUE_TB_WIN_IN_MAX_PLY - 1` (=31743) → `28000` に変更
- [x] `VALUE_MAX_EVAL`: `VALUE_SUPERIOR` (=31743) → `27000` に変更
- [x] `VALUE_KNOWN_WIN`: 未定義 → `VALUE_MATE_IN_MAX_PLY - 1000` (=30744) を追加
- [x] `DEPTH_ENTRY_OFFSET`: `-3` → `-7` に変更 (tanuki- の `DEPTH_OFFSET` と同値)
- [x] `gensfen2019` の `write_minply`: `1` → `16` に変更 (depth ベース gensfen は元から 16)
- [x] HKP256 / HKP768 の両バリアントでクリーンビルド確認

**変更ファイル (V8.50):**

| ファイル | 変更内容 |
|---|---|
| `source/types.h` | `VALUE_KNOWN_WIN` 追加、`VALUE_SUPERIOR` を 28000 に、`VALUE_MAX_EVAL` を 27000 に、`DEPTH_ENTRY_OFFSET` を -7 に変更。各定数に V8.50 original 値をコメントで記録 |
| `source/learn/learner.cpp` | `gensfen2019` の `write_minply` デフォルトを 1 → 16 に変更 |

### Phase 6 — コミット

- [x] V8.50 の変更を commitlint 形式でコミット
  - `fix(evallearn)`: multi_think.cpp の crash fix + tanuki- ポート
  - `feat(gensfen)`: seed パラメータ追加
  - `refactor(tt)`: tanuki-dr5 互換 TT 実装
- [x] tanuki- の変更をコミット
  - `fix(linux)`: Linux 互換パッチ + HKP768
  - `feat(gensfen)`: seed パラメータ追加
- [x] 比較スクリプト (`scripts/compare_gensfen.py`) をコミット
- [x] プラン文書の最終更新

---

## コード比較結果

### gensfen (depth ベース) パラメータ比較

| 項目 | V8.50 | tanuki-dr5 | 一致 |
|---|---|---|---|
| デフォルト loop_max | 8,000,000,000 | 8,000,000,000 | ✅ |
| デフォルト eval_limit | 3000 (mate_in(2)=31998 でキャップ) | 3000 (同左) | ✅ |
| デフォルト search_depth | 3 | 3 | ✅ |
| デフォルト write_minply | 16 | 16 | ✅ (V8.50 original: gensfen=16, gensfen2019=1 → 16 に変更) |
| デフォルト write_maxply | 400 | 400 | ✅ |
| PackedSfenValue 構造体 | 40バイト | 同左 | ✅ |
| SfenWriter バッファサイズ | 5000 | 5000 | ✅ |
| ランダムムーブ (count/min/max ply) | 5 / 1-24 | 5 / 1-24 | ✅ |
| seed パラメータ | 追加済み | 追加済み | ✅ |

### TT (置換表) 比較

| 項目 | V8.50 (変更後) | tanuki-dr5 | 一致 |
|---|---|---|---|
| TTEntry フィールド順 | key16, move16, value16, eval16, genBound8, depth8 | 同左 | ✅ |
| save() API | `save(Key, Value, bool, Bound, Depth, Move, Value)` | 同左 | ✅ |
| probe() API | `TTEntry* probe(Key, bool&)` | 同左 | ✅ |
| save() 上書き条件 | `BOUND_EXACT \|\| key不一致 \|\| depth優位` | 同左 | ✅ |
| PV ボーナス / relative_age 条件 | なし | なし | ✅ |
| 置換エントリー選択式 | `depth8 - ((263+gen-genBound8)&0xF8)` | 同左 | ✅ |
| メモリ管理 | LargeMemory RAII | 同左 | ✅ |

### 統計比較 (seed=12345, depth=9, 1000 レコード, TT 統一後)

| 指標 | V8.50 | tanuki-dr5 | 差異 |
|---|---|---|---|
| score 平均 | 58.93 | -21.13 | 80.06 |
| score 標準偏差 | 3275 | 3828 | 552 |
| gamePly 平均 | 81.82 | 80.83 | 0.99 |
| 勝率 | 50.2% | 50.4% | 0.2% |

### 残存する差異 (探索アルゴリズム)

V8.50 と tanuki-dr5 は探索エンジンのバージョンが異なる (V8.50 vs 5.33) ため、以下の点で bit-identical 出力は得られない:

- 枝刈り条件 (null move pruning, futility pruning, LMR 等) の閾値
- 延長条件 (singular extension 等)
- move ordering のヒューリスティクス
- 静止探索の実装詳細

これらは同一の TT/gensfen パラメータを使っても異なる探索結果をもたらすが、統計分布は近似する。

### 定数比較 (Phase 5b で統一済み)

| 定数 | V8.50 original | tanuki-dr5 | V8.50 変更後 | 一致 |
|---|---|---|---|---|
| VALUE_SUPERIOR | 31743 (`VALUE_TB_WIN_IN_MAX_PLY-1`) | 28000 | 28000 | ✅ |
| VALUE_MAX_EVAL | 31743 (`VALUE_SUPERIOR`) | 27000 | 27000 | ✅ |
| VALUE_KNOWN_WIN | 未定義 | 30744 (`VALUE_MATE_IN_MAX_PLY-1000`) | 30744 | ✅ |
| DEPTH_ENTRY_OFFSET / DEPTH_OFFSET | -3 | -7 | -7 | ✅ |

---

## 成功判定基準

- [x] V8.50 evallearn ビルド通過 (全バリアント)
- [x] tanuki-dr5 Linux ビルド通過 (HKP256)
- [x] gensfen クラッシュ (SIGSEGV) 解消 (gensfen + quit で正常終了)
- [x] gensfen (depth ベース) が両バイナリで完走
- [x] seed 固定で同一エンジンの出力が決定的 (MD5 一致)
- [x] score 平均の差異 < 100, gamePly 平均の差異 < 5 (1000 レコード)
- [x] shuffle_kifu (ApplyQSearch=true) が V8.50 で完走
- [x] TT 実装が tanuki-dr5 互換 API に統一
- [x] 定数 (VALUE_SUPERIOR, VALUE_MAX_EVAL, VALUE_KNOWN_WIN, DEPTH_ENTRY_OFFSET) が tanuki-dr5 と同値
- [x] 全変更がコミット済み
