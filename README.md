# kaguya — NNUE 学習パイプライン

将棋 NNUE (Efficiently Updatable Neural Network) の教師局面生成・学習・評価を一気通貫で行うためのツールキット。

## 概要

YaneuraOu V8.50 をベースに、tanuki-dr5 互換の gensfen / shuffle_kifu パイプラインを構築。Claude Code のスラッシュコマンド (`/gensfen`, `/train`, `/eval`) で対話的に実行できる。

## パイプライン

```
/gensfen                          /train                        /eval
   │                                 │                             │
   ▼                                 ▼                             ▼
YaneuraOu gensfen (depth探索)   PyTorch Lightning            YaneuraOu 対局
   │                                 │                             │
   ▼                                 ▼                             ▼
shuffle_kifu (ApplyQSearch)     nn.bin 出力                   Elo ±95% CI
   │
   ▼
data/<name>/shuffled.bin
```

## ディレクトリ構成

```
engines/
  eval/{kp256,hkp256,hkp768}/nn.bin   teacher eval
  book/user_book1.db                   定跡 DB
  YaneuraOu-*_learn                    evallearn バイナリ
vendor/
  YaneuraOu/                           V8.50 (learn ブランチ, tanuki-dr5 互換改修済み)
scripts/
  build_yaneuraou.sh                   ビルドヘルパー (6バリアント対応)
  compare_gensfen.py                   gensfen 出力比較スクリプト
data/
  <name>/raw/                          gensfen 生データ
  <name>/shuffled.bin                  シャッフル + qsearch leaf 変換済み
docs/
  plans/                               改修プラン・差分記録
  train/                               学習方針ドキュメント
```

## 対応バリアント

| variant | アーキテクチャ | FV_SCALE | eval |
|---|---|---|---|
| `kp256` | K-P 256-32-32 | 16 | あり |
| `hkp256` | HalfKP 256x2-32-32 | 20 | あり |
| `hkp768` | HalfKP 768x2-16-64 | 40 | あり |
| `hkp512` | HalfKP 512x2-16-32 | 16 | — |
| `hkp1024` | HalfKP 1024x2-8-32 | 16 | — |
| `hkp1024_64` | HalfKP 1024x2-8-64 | 16 | — |

## クイックスタート

### エンジンビルド

```bash
scripts/build_yaneuraou.sh hkp768 --build evallearn
```

### 教師局面生成

```bash
# Claude Code から
/gensfen
# → variant, count, depth を対話的に選択
# → gensfen + shuffle_kifu (ApplyQSearch=true) を自動実行
```

### 手動実行

```bash
engines/YaneuraOu-HalfKP_768x2-16-64_learn <<EOF
setoption name EvalDir value engines/eval/hkp768
setoption name FV_SCALE value 40
setoption name BookDir value engines/book
setoption name BookFile value user_book1.db
setoption name Threads value $(nproc)
setoption name USI_Hash value 8192
isready
gensfen depth 9 loop 1000000 save_every 1000000 output_file_name data/run1/raw/gen
quit
EOF
```

## YaneuraOu V8.50 への改修内容

tanuki-dr5 との互換性のために以下を変更済み:

- **TT (置換表)**: `TTData`/`TTWriter` tuple API → `TTEntry*` + `bool& found` API に全面置換
- **TT メモリ管理**: `LargeMemory` RAII クラス導入
- **定数統一**: `VALUE_SUPERIOR`=28000, `VALUE_MAX_EVAL`=27000, `VALUE_KNOWN_WIN`=30744, `DEPTH_ENTRY_OFFSET`=-7
- **gensfen**: seed パラメータ追加、write_minply デフォルト統一 (16)
- **shuffle_kifu**: tanuki-dr5 の `ShuffleKifu` + `ApplyQSearch` を移植
- **クラッシュ修正**: `MultiThink::go_think()` 内の `is_ready(true)` による TT メモリ破壊を解消

変更箇所の詳細は `docs/plans/gensfen_parity_with_tanuki.md` を参照。

## 要件

- Ubuntu 24.04 / g++ 13.3
- AVX2 対応 CPU
- OpenMP (libgomp1)

## ライセンス

YaneuraOu のライセンスに準拠。
