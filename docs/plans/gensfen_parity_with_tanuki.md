# gensfen / shuffle_kifu を tanuki-dr5 と V8.50 で一致させるプラン

## 背景

`vendor/tanuki-` を `tanuki-dr5_production-learner` ブランチで取り込み、`vendor/YaneuraOu` の `learn` ブランチに `source/learn` 周り + `tanuki_progress` / `tanuki_kifu_{reader,writer,shuffler}` を移植済み。

**比較対象のコマンド**: 両エンジンが共通で持つ `gensfen2019` (nodes_limit ベース) と `shuffle_kifu` (ApplyQSearch=true)。旧 `gensfen` (depth ベース) は tanuki- 側にないため比較対象外。

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

## コード比較結果

### gensfen2019 の実装比較

| 項目 | V8.50 | tanuki-dr5 | 一致 |
|---|---|---|---|
| デフォルト loop_max | 8,000,000,000 | 8,000,000,000 | ✅ |
| デフォルト eval_limit | 32000 | 32000 | ✅ |
| デフォルト search_depth | 24 | 24 | ✅ |
| デフォルト nodes_limit | 10000 | 10000 | ✅ |
| デフォルト write_minply | 1 | 1 | ✅ |
| デフォルト write_maxply | 300 | 300 | ✅ |
| デフォルト book_file_name | book/flood2018.sfen | book/flood2018.sfen | ✅ |
| eval_limit のキャップ | なし (そのまま使用) | なし (そのまま使用) | ✅ |
| 勝敗判定ロジック | mated/DeclarationWin/eval_limit | 同左 | ✅ |
| game_result エンコード | 1 (勝ち) / -1 (負け) | 同左 | ✅ |
| PackedSfenValue 構造体 | 40バイト (last_position:1, entering_king:1) | 同左 | ✅ |
| SfenWriter バッファサイズ | 5000 | 5000 | ✅ |
| ランダムムーブ | book から2手 | 同左 | ✅ |
| book の最大 ply | 32 | 32 | ✅ |

### 定数の差異 (gensfen2019 には影響しない)

| 定数 | V8.50 | tanuki-dr5 | 影響範囲 |
|---|---|---|---|
| VALUE_SUPERIOR | 31743 | 28000 | learner のみ |
| VALUE_MAX_EVAL | 31743 | 27000 | learner のみ |
| VALUE_KNOWN_WIN | N/A | 30744 | tanuki- 固有 |

**結論**: gensfen2019 のコードパスでは VALUE_SUPERIOR / VALUE_MAX_EVAL は参照されない。同一パラメータ・同一 nn.bin であれば、乱数 seed の違いを除いて出力の統計分布は一致するはず。

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
  - `Threads.set()` は NUMA 対策で毎回全スレッドを delete → recreate する
  - TT の `std_aligned_alloc` メモリが無効化され `TT.clear()` (memset) で SIGSEGV
  - V8.50 のアップストリームバグ (tanuki- パッチ起因ではない)
- [x] 修正 1: `is_ready(true)` をコメントアウト (初回 isready で初期化済み)
- [x] 修正 2: `Options` 全体の復元を `BookOnTheFly` のみの復元に変更 (ハンドラ付きオプションの副作用回避)
- [x] gensfen 完走確認 (100 positions, Threads=1)
- [x] プロダクションビルド (`build_yaneuraou.sh hkp256 --build evallearn`, LTO 有効)
- [ ] quit 時の `free(): invalid pointer` (glibc global destructor 順序) — gensfen/shuffle_kifu 動作には影響なし、低優先度

### Phase 2 — tanuki-dr5 の Linux ビルド

- [x] Windows 依存コードの修正 (`_mkdir` → `mkdir`, `_MAX_PATH` → `PATH_MAX`, `_fseeki64` → `fseeko`, `_ftelli64` → `ftello`)
- [x] HKP256 での evallearn ビルド通過 (エンジン ID: YaneuraOu NNUE 5.33)
- [x] HKP768 エディション追加 (`nnue_architecture.h` + アーキテクチャヘッダ)
- [ ] tanuki- バイナリで gensfen2019 が完走することを確認

### Phase 3 — gensfen2019 の実機比較

- [x] gensfen2019 のソースコード比較: パラメータ・ロジック・出力フォーマット全て同一
- [ ] 両バイナリで gensfen2019 を実行
  - 条件: `gensfen2019 search_depth 9 nodes_limit 10000 loop 10000 output_file_name <output> eval_limit 32000 write_minply 1 write_maxply 300 book_file_name no_book`
  - Threads=1, Hash=1024, EvalDir=engines/eval/hkp256
- [ ] 出力ファイルの基本検証
  - ファイルサイズが 40 の倍数であること
  - レコード数が 10000 以下であること (eval_limit 超えで途中打ち切りの局面あり)
- [ ] 出力比較スクリプト (`scripts/compare_gensfen.py`) の作成
  - 40 バイトレコード読み込み
  - フィールド別ヒストグラム: score, gamePly, game_result
  - score 分布 (特に ±eval_limit 付近)
  - 統計量 (平均, 中央値, 標準偏差) の比較
- [ ] 統計分布が一致することを確認

### Phase 4 — shuffle_kifu の実機比較

- [ ] gensfen2019 で生成した raw データに対して shuffle_kifu を実行 (ApplyQSearch=true)
  - V8.50: `KifuDir=data/compare_v850/raw`, `ShuffledKifuDir=data/compare_v850/shuffled`
  - tanuki-: 同設定
- [ ] shuffled.bin のレコード数が元データと一致することを確認
- [ ] ApplyQSearch 適用後の score 分布を比較
  - qsearch leaf 置換で score が変わらないことを確認
  - game_result の反転が正しいことを確認
- [ ] 両エンジンの shuffle_kifu 出力が統計的に等価であることを確認

### Phase 5 — 差異がある場合の V8.50 パッチ (条件付き)

Phase 3/4 で統計的な差異が検出された場合のみ実施:

- [ ] 差異の原因特定
- [ ] V8.50 への最小パッチ適用
  - `VALUE_SUPERIOR` は gensfen2019 に影響しないため変更不要の見込み
  - 旧 `gensfen` は比較対象外
- [ ] パッチ適用後に再比較

### Phase 6 — コミットと整理

- [ ] V8.50 の変更を commitlint 形式でコミット
  - multi_think.cpp の crash fix
  - tanuki- ポート (kifu_reader, kifu_writer, kifu_shuffler, progress)
  - usi.cpp / usi_option.cpp の統合
  - learn.h / learning_tools.h の構造体変更
  - learner.cpp の tanuki- パッチ (SfenReader, gaussian lambda, etc.)
- [ ] 比較スクリプトをコミット
- [ ] プラン文書の最終更新

---

## 成功判定基準

- [x] V8.50 evallearn ビルド通過 (全バリアント)
- [x] tanuki-dr5 Linux ビルド通過 (HKP256)
- [x] gensfen クラッシュ (SIGSEGV) 解消
- [ ] gensfen2019 が両バイナリで完走
- [ ] score 分布の統計量 (平均/標準偏差/四分位) が ±5% 以内で一致
- [ ] shuffle_kifu (ApplyQSearch=true) が両バイナリで完走
- [ ] 全変更がコミット済み

## リスクと対策

| リスク | 対策 |
|---|---|
| book_file_name のデフォルト `flood2018.sfen` が存在しない | `no_book` を指定して定跡なしで実行 |
| seed 固定不可で bit-identical 比較ができない | 統計分布比較に切り替え (ヒストグラム + 統計量) |
| quit 時の `free(): invalid pointer` | gensfen/shuffle_kifu 動作には影響なし。低優先度で別途対応 |
| tanuki- の gensfen2019 が book なしでクラッシュ | `no_book` ではなく空の book ファイルを用意 |
