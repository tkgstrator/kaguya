# BucketHalfKP 系 特徴量

## 背景

HalfKP ([hkp.md](./hkp.md)) は強いが 125388 次元と重く、WASM ではメモリ/転送量の制約がきつい。
KP ([kp.md](./kp.md)) は軽くピーク +182 Elo まで伸びるが、ピーク到達に 45B pos かかり HalfKP (+342) との差は依然大きい。
この 2 つの中間として「玉の位置を粗視化して次元を落とす」アプローチが Bucket 系 (BucketHalfKP / MirrorBucketHalfKP)。

## BucketHalfKP (9 bucket)

### 定義
玉の 81 マスを 3×3 ブロック = 9 バケットに圧縮。各バケット内の玉はすべて同じ重みを共有する。

実装: [`features/bucket_half_kp.h`](../../YaneuraOu/source/eval/nnue/features/bucket_half_kp.h)

```cpp
static int GetBucket(Square king_sq) {
    int file = (int)file_of(king_sq);  // 0..8
    int rank = (int)rank_of(king_sq);  // 0..8
    return (file / 3) * 3 + (rank / 3);  // 0..8
}
```

| 量 | 値 | 計算 |
|---|---|---|
| kPieceRange | 1548 | `fe_end` |
| kNumBuckets | 9 | 3 × 3 |
| kDimensions | **13932** | 1548 × 9 |
| active 数 | 38 | `PIECE_NUMBER_KING` |

Refresh Trigger: `kFriendKingMoved` (バケットを跨ぐ玉移動で全再計算)

### ネットワーク
[`architectures/bucket-half-kp_256x2-32-32.h`](../../YaneuraOu/source/eval/nnue/architectures/bucket-half-kp_256x2-32-32.h) で HalfKP 256 系と同じ 256-32-32-1 トポロジ。

## MirrorBucketHalfKP (6 bucket)

### 定義
BucketHalfKP を左右対称化。`sym_file = min(file, 8-file)` で file 0 と 8、1 と 7、... を同一視。玉が file ≥ 5 のときは BonaPiece 側もミラー反転する。

実装: [`features/mirror_bucket_half_kp.h`](../../YaneuraOu/source/eval/nnue/features/mirror_bucket_half_kp.h)

```cpp
int sym_file = std::min(file, 8 - file);  // 0..4
int col = sym_file / 3;   // 0 or 1
int row = rank / 3;       // 0, 1, 2
return col * 3 + row;     // 0..5
```

`col=0` が端寄り (file 0-2 / 6-8)、`col=1` が中央 (file 3-5)。`NeedsMirror(king_sq) = file >= 5` でミラー判定、`MirrorBonaPiece(p)` で盤上駒を反転 (持ち駒は不変)。

| 量 | 値 |
|---|---|
| kDimensions | **9288** (1548 × 6) |

### 位置付け
左右対称性を活用して次元をさらに削減 (13932 → 9288)。BucketHalfKP の約 67%、HalfKP の ~7.4%。
L1 = 256/512/1024 の 3 サイズを実装。

## BucketHalfKP がなぜ弱いのか

BHKP256 の実測 -50 Elo は理論的にも説明がつく。

### 1. バケット死に (実効パラメータが ~44%)
9 バケットのうち、実戦で頻繁に訪問されるのは玉の定位置 (穴熊、美濃、矢倉の玉) に対応する数個のみ。
Shogi の序中盤で玉は segment `(rank ≤ 2)` に集中するため、少なくとも 3 バケット (rank/3 = 2 側) は実戦ではほぼ死ぬ。castling の流派 (居飛車穴熊 → 2, 振り飛車美濃 → 5 or 8) に応じて 4-5 バケット (約 5/9) が有効。
→ **学習パラメータの 44% (4/9) しか勾配信号を受けない**。同じ次元の HalfKP (125388 すべて active な可能性) と比べ、実効モデル容量が激減。

### 2. 3×3 の境界不連続
玉が 3g → 3h に 1 マス移動するだけでバケット 0 → 1 を跨ぐことがある。
同じ「中住まい美濃」でも 1 マスの位置差で全く別の重みを使うため、
- 重み共有の連続性が壊れる
- データが希薄な境界付近の勾配が不安定
→ KP (玉位置 81 独立) や HalfKP (81 独立, joint) と比べ、**bucket 境界のアーチファクト** が出やすい。

### 3. 異なる戦型が同一バケットに衝突
bucket 2 (file 0-2, rank 6-8) には居飛車穴熊 (玉 9i/8i/7i) も振り飛車玉 (8h 美濃) も同じバケットに入る。
戦型ごとに最適な駒の価値が異なるにも拘わらず、同じ FT 重みで近似せざるを得ない → 平均化されて粗い学習になる。

### 4. HalfKP と KP の悪いところ取り
- HalfKP に対して: 玉位置の解像度を 81 → 9 に落としており、joint 表現の表現力が落ちている。
- KP に対して: 次元は 1710 → 13932 で 8 倍重い。
→ HalfKP の表現力でも KP の軽さでもない**中途半端なポジション**になっている。

## 評価結果

### 評価条件 (共通)

- 対戦相手: `kp256_2019` (eval/kp256/nn.bin, FV_SCALE=20, 固定ベースライン)
- 探索条件: byoyomi 500ms, threads 4, hash 1024 MB
- 対局数: 1000 / 開始局面: data/balanced_ply32.sfen

### bhkp256 vs kp256_2019 (BucketHalfKP 9 bucket)

| 項目 | 値 |
|---|---|
| challenger | `bhkp256` (epoch=14, 5.8 B pos) |
| opponent   | `kp256_2019` (eval/kp256/nn.bin) |
| 対局数    | 1000 |
| 探索条件   | byoyomi 500ms, threads 4, hash 1024 MB |
| W / L / D | 未記録 |
| Elo       | **-50 ± 22** (95% CI) |

**所見**: HKP256 (+342) / KP256 ピーク (+182) 双方に負ける期待外れ。CI が 0 を跨がず有意な劣化で、バケット化による情報損失が致命的だったことを示す。原因は下記「BucketHalfKP がなぜ弱いのか」4 観点。MirrorBucketHalfKP (6 bucket) は未計測 (deprecated)。

## 次のアクション

BucketHalfKP の粗視化失敗を受け、81 マス解像度を保ったまま左右対称性のみを利用する `MirrorHalfKP` (45 位置、69660 次元) を新規実装する方針。詳細は [mhkp.md](./mhkp.md) 参照。

## 関連ファイル

- [`features/bucket_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — BucketHalfKP 実装
- [`features/mirror_bucket_half_kp.{h,cpp}`](../../YaneuraOu/source/eval/nnue/features/) — Mirror bucket 実装 (6 bucket 版)
- [kp.md](./kp.md), [hkp.md](./hkp.md), [mhkp.md](./mhkp.md) — 関連特徴量
