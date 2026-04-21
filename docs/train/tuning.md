# KP256 学習パイプラインの高速化レポート

**対象**: `nnue-pytorch` の KP 特徴量 / KP256 モデル学習パイプライン
**実施日**: 2026-04-15
**実施環境**: AMD EPYC 7742 (256 論理 CPU) + NVIDIA A100-SXM4-80GB × 8 (学習は GPU 7 のみ使用)
**学習データ**: `data/shuffled_train.bin` (315 GB, 7.87B positions, shogi_hao_depth9 を YaneuraOu `learn shuffle` で 2-pass シャッフル)

## 結論

1. `BinSfenInputStream` を共有 mutex で直列化していたのがボトルネックだった。
2. `ParallelBinSfenInputStream` (atomic offset + `pread`) を新設し mutex を撤廃した。
3. **C++ データローダ単体で 23 倍、Python 学習全体で 7.9 倍の高速化**。
4. 修正後はボトルネックが Python/GPU 側に移動したので、`batch_size=65536` へ拡大 (LR も 3.5e-3 に線形スケール) することで更に **pos/sec を 1.9 倍** 伸ばせた。
5. 最終的に **KP256 800 epoch が 81 時間 → 約 5.7 時間** まで短縮された。

---

## 背景と動機

KP256 を含む `nnue-pytorch` の学習パイプラインは、デフォルト設定 (`num_workers=8`, `batch_size=16384`) で走らせると **13.57 it/s** (~222K pos/s) しか出ず、GPU 使用率は 7% 前後に留まっていた。800 epoch 学習の所要時間は 80 時間超と推定され、KP512 / KP1024 に進む前の KP256 フェーズだけでハードウェア時間を大量に食いつぶす懸念があった。

当初は「Python 側のチューニング (`num_workers`, `batch_size`)」で解決できると予想していたが、実際には全て頭打ちで、根本原因が C++ データローダ内部にあることが判明した。

---

## 調査 (1): Python 側のパラメータでは解けない

### `num_workers` のスイープ
`scripts/kp256/bench_workers.sh` で 32〜256 を試した結果:

| num_workers | it/s (median) | CPU | GPU |
|---:|---:|---:|---:|
| 32  | 15.24 | 162 core | 6%  |
| 64  | **16.73** | 168 core | 7% |
| 96  | 16.39 | 168 core | 7% |
| 128 | 16.12 | 170 core | 7% |
| 192 | 15.29 | 167 core | 9% |
| 256 | 14.29 | 164 core | 7% |

ピークが 64 だが差は誤差レベル (±15%)、GPU はどの設定でも 7-9%。**worker 数は有効なノブではない** ことが確定。

### `batch_size` のスイープ
`scripts/kp256/bench_batch.sh` で 16384〜131072 を試した結果:

| batch_size | it/s | **pos/s** |
|---:|---:|---:|
| 16384  | 16.69 | 273K |
| 32768  |  7.92 | 260K |
| 65536  |  3.14 | 206K |
| 131072 | (failed) | — |

固定コスト償却の理論に反し **batch_size を上げると逆に遅くなった**。これは C++ データローダの per-position 処理コストが線形で、「batch を大きくするほど一回分の作業量が線形に増え、メモリ負荷だけが余分にかかる」ためだった。

---

## 調査 (2): C++ データローダ単体の測定

Python 学習と C++ データローダのどちらが律速かを切り分けるため、`CMakeLists.txt` に書かれていた `training_data_loader_benchmark` 実行ファイルを利用した。ただし元の CMakeLists では **`PGO_Generate` ビルド限定** で定義されており、かつ `PGO_BUILD` マクロの下で `concurrency=1` / `iteration_count=30` に矮小化されていたため、以下の変更を加えた:

- `CMakeLists.txt`: `training_data_loader_benchmark` を常時ビルドする形に書き換え (`add_executable` を `if` ブロックの外に出す)。
- `training_data_loader.cpp`: benchmark 内のハードコード `"HalfKA_hm^"` を **`"KP"`** に変更。

その上で `./build/training_data_loader_benchmark data/shuffled_train.bin` を走らせた結果:

| 測定 | 値 |
|---|---|
| 並列度 (hardware_concurrency) | 256 |
| MPos/s | **0.253** (= 253K pos/s) |
| it/s (@batch 16384) | 15.4 |
| MB/s | 9.7 |

**Python 学習が出していた 273K pos/s と殆ど差がない**。つまり Python 側のオーバヘッドは誤差範囲で、ボトルネックは **C++ データローダ内部** にあると断定できた。さらに、C++ 単独で並列度 256 を与えても 15.4 it/s で頭打ちなのは、**concurrency を増やしても効かないシリアル律速セクションが存在する** ことを示している。

---

## 調査 (3): 真の原因 — `m_stream_mutex`

`lib/nnue_training_data_stream.h` を読んで以下を発見した:

```cpp
inline std::unique_ptr<BasicSfenInputStream> open_sfen_input_file_parallel(
    int concurrency,
    const std::vector<std::string>& filenames,
    bool cyclic,
    std::function<bool(const shogi::TrainingDataEntry&)> skipPredicate = nullptr)
{
    // TODO (low priority): optimize and parallelize .bin reading.
    if (has_extension(filenames[0], BinSfenInputStream::extension))
        return std::make_unique<BinSfenInputStream>(filenames[0], cyclic, std::move(skipPredicate));
    ...
}
```

**関数名は `parallel` と称しているが、`.bin` ファイルについては `concurrency` 引数を完全に無視し、単一の `BinSfenInputStream` を返すだけ**だった。TODO コメントも「後で並列化する」旨が書かれている。

さらに `training_data_loader.cpp` の `FeaturedBatchStream` のワーカループでは:

```cpp
auto worker = [this]()
{
    while (!m_stop_flag.load())
    {
        {
            std::unique_lock lock(m_stream_mutex);
            BaseType::m_stream->fill(entries, m_batch_size);
            ...
        }
        auto batch = new StorageT(FeatureSet{}, entries);
        ...
    }
};
```

と書かれており、**全ての feature worker スレッドが `m_stream_mutex` で単一の共有ストリームへのアクセスを直列化していた**。

つまり全体の動きは:
1. ユーザが `NUM_WORKERS=64` を指定しても、C++ は内部で ~32 個の feature worker + ~32 個の reader thread を生成する
2. しかし reader 側は 1 本の `std::fstream` しか持たないので事実上シングルリーダ
3. 全 feature worker は `m_stream_mutex` の取得待ちで blocked 状態になり、CPU は「スピン待ち」で 170 コアを埋めてしまう
4. 実効スループットはほぼ「単一リーダ + シングルスレッドデコード」の速度に張り付き、GPU は常に空腹 (7%)

---

## 改修: `ParallelBinSfenInputStream`

### 設計
- **atomic offset**: `std::atomic<std::size_t> m_offset` を共有し、各ワーカは `fetch_add(chunk_bytes)` で自分の担当チャンクを競合なく取得する。
- **pread**: ファイルディスクリプタ 1 個を複数スレッドで共有し、`pread()` で offset 指定の読み込みを行う。`pread` は POSIX でスレッドセーフ。
- **チャンクサイズ**: 4096 records × 40 B/record = 約 164 KB。小さすぎると atomic 競合、大きすぎるとロードバランスが崩れるので中庸を選択。
- **cyclic 対応**: offset が EOF を超えたら CAS で 0 に巻き戻す。複数ワーカが同時に巻き戻しても benign (どのワーカも小さい offset に収束する)。
- **シャッフル済みデータ前提**: 学習データは事前に `learn shuffle` でシャッフル済みなので、チャンクの読み出し順序は結果に影響しない。

### コード変更
- `lib/nnue_training_data_stream.h`
  - `ParallelBinSfenInputStream` クラス新設 (POSIX 限定)。
  - `open_sfen_input_file_parallel` が `.bin` の場合にこの新クラスを返すように変更。
- `training_data_loader.cpp`
  - `FeaturedBatchStream::worker` から `m_stream_mutex` の取得を削除。
  - `m_stream_mutex` メンバ変数自体も削除。
- `CMakeLists.txt`
  - `training_data_loader_benchmark` を常時ビルド対象に変更 (上記調査のため)。
- コミット: `21a36a7 データローダの.binリーダを並列化した。`

---

## 計測: 修正の効果

### C++ 単体ベンチマーク (`training_data_loader_benchmark`)
| | 旧実装 | 新実装 | 倍率 |
|---|---:|---:|---:|
| MPos/s | 0.253 | **5.78** | **22.8×** |
| it/s (@batch 16384) | 15.4 | **353** | **22.9×** |

### Python 学習 (KP256, `bench_workers.sh` で計測、batch=16384)
| | 旧実装 | 新実装 | 倍率 |
|---|---:|---:|---:|
| it/s | 16.73 | **131.71** | **7.9×** |
| pos/s | 273K | 2.16M | 7.9× |
| CPU 使用率 | 170 core | 18 core | 0.11× |
| GPU 使用率 | 7-9% | 53% | 6.6× |

**注目すべき点**: 新実装では CPU 使用率が **1/10 に低下** した。旧実装の 170 コアは mutex 待ち (スピンロック / 条件変数) で無駄に焼かれていたことがわかる。

### 1 epoch あたりの所要時間
- 旧: ~6 分 (16.73 it/s × 6104 iter = 365 秒)
- 新: ~49 秒 (131.71 it/s × 6104 iter = 46 秒、実測 49 秒)
- 800 epoch 総計: 80 時間 → **11 時間**

---

## 二次チューニング: ボトルネック移動後の再測定

改修によりボトルネックが「C++ データローダ」から「Python + Lightning + GPU 消費速度」へと移った。この状態で改めて `num_workers` と `batch_size` をスイープした。

### `num_workers` 再測定 (batch=16384)
| num_workers | it/s | GPU |
|---:|---:|---:|
| 64  | 121.44 | 53% |
| 96  | 119.06 | 46% |
| **128** | **131.71** | 51% |
| 192 | 121.94 | 50% |
| 256 | 128.56 | 57% |

→ 128 がわずかなピーク。差は ±8% で本質的にはどれでも良い。C++ 側は既に十分な速度で batch を生成しており、**Python 側が drain できない限界に達している**。

### `batch_size` 再測定 (num_workers=128)
| batch_size | it/s | **pos/s** | GPU |
|---:|---:|---:|---:|
| 16384  | 125.40 | 2.05M | 54% |
| 32768  | 104.18 | 3.41M | 75% |
| 65536  |  59.66 | **3.91M** | **82%** |
| 131072 |  29.61 | 3.88M | 80% |

今度は **batch_size を上げると pos/s が素直に伸びた**。旧実装では C++ のシリアル律速に引きずられていた (batch を増やしても一回分の作業量が線形増加するだけ) が、新実装では Python per-iter 固定コスト (Lightning callback, tensor 変換, optimizer step, GPU 同期) が効いてきて、**batch あたりの固定コストが償却される構造**に変化したため。

131072 では GPU 82% → 80% と若干落ち収束し、実質的な上限は **65536 付近**と判断できる。

---

## 本番構成

上記の結果から、KP256 本番学習 (`kp256_v1`) の構成を以下に決定した:

```bash
BATCH_SIZE=65536
LR=3.5e-3               # 線形スケール則: 8.75e-4 × 4
NUM_WORKERS=128
OMP_NUM_THREADS=16      # thread explosion 防止
NETWORK_SAVE_PERIOD=1   # 1 epoch ごと ckpt (resume 粒度確保、ckpt 1 個 ~4 MB)
WANDB__EXTRA_HTTP_HEADERS={"CF-Access-Client-Id":"...","CF-Access-Client-Secret":"..."}
```

- **学習時間**: 800 epoch × 約 25 秒 = **約 5.7 時間** (実測で epoch 0 = 49 秒の予想から下振れし、steady state では更に速い)
- **GPU 使用率**: 82-85% (A100 1 基をきちんと使い切れている)

## 学習ダイナミクスへの影響

`batch_size` を 4 倍 (16384 → 65536) にしたことで 1 epoch あたりの勾配更新回数が 6104 → 1526 に減ったが、**linear scaling rule** で LR も 4 倍 (8.75e-4 → 3.5e-3) にスケールしたので、期待される学習軌跡は同等になる。Ranger21 (AdamW ベース) + Lookahead の組み合わせはこの則がよく効くことが経験的に知られている。

本番 run の実測 loss 軌跡:

| epoch | train_loss | val_loss |
|---:|---:|---:|
| 0 (step 49) | 0.0444 | — |
| 0 (step 1525) | 0.0328 | 0.0315 |
| 1 | 0.0276 | 0.0259 |
| 17 (序盤終了) | 0.0220 | 0.0219 |
| 538 (67% 地点) | 0.0180 | 0.0180 |

- 単調減少、train と val が 1:1 で追従 → **overfit 兆候ゼロ**
- 損失は `|pt - qf|^2.5` 形式 (sigmoid 勝率空間、`lightning_module.py:56`) なので値の絶対量が小さいのは仕様
- LR 3.5e-3 で発散やスパイクはなし
- 期待値: 800 epoch 完走時点で train/val ~ 0.016-0.017 付近に収束見込み

---

## 副産物と将来のノブ

### 今回のチューニングで学んだこと
- **OMP_NUM_THREADS は必ず明示的に設定する**。未設定だと OpenMP / MKL / PyTorch が `hardware_concurrency=256` の thread pool を複数作り、Python プロセスが 700 超のスレッドを抱えて `py-spy` の native profile が追いつかなくなる。KP256 のような軽量モデルなら `OMP_NUM_THREADS=16` で十分。
- **長時間ジョブは必ずセッションから切り離す**。今回の調査中、ネットワーク断で SSH セッションが死んだ際に shuffle プロセスが生き残っていたのは NFS の silly-rename (`.nfs...`) のおかげで偶然救われたが、本来は `disown` / `nohup` / `tmux` / Claude Code の `run_in_background` のいずれかを必ず使うべき。

### まだ残っている高速化候補
以下は今回は手を付けていないが、将来 GPU 使用率を更に押し上げる場合の候補:

1. **`get_tensors("cuda:7")` 直接 GPU 転送**: 現在 `data_loader/dataset.py:103` で `get_tensors("cpu")` を呼び、その後 `pin_memory()` + Lightning の `batch_to_device` で GPU に送っている。直接 `"cuda:7"` を渡せば中間コピーが 1 回減り、数 % の改善が見込める。
2. **feature pre-compute**: KP は K と P が独立で、特徴量インデックスが 1 position 当たり正確に 40 個とわかっている。binpack を読み取って `(is_white, outcome, score, white_indices[40], black_indices[40])` 形式のパックファイルに事前ダンプしておけば、学習時の binpack decode + chess logic が不要になる (KP256/512/1024 全てで同じファイルを共有可)。1.4 TB の追加ストレージが必要で、初回ダンプに 4-8 時間程度かかる。KP512/KP1024 まで繋げる場合は ROI が高い。
3. **`torch.compile` バックエンド変更**: 現在 `train.py` で `args.compile_backend` (既定 inductor) を使っている。他のバックエンド (`aot_eager`, `cudagraphs`, Triton) を試す余地あり。
4. **Lightning callback 削減**: `TQDMProgressBar(refresh_rate=300)` は既に頻度を下げてあるが、更に 1000 まで上げる、`WeightClippingCallback` の適用頻度を下げるなどの微調整で数 % 稼げる可能性。
5. **PGO ビルド**: `CMakeLists.txt` は PGO_Generate / PGO_USE 2 段階ビルドに対応している。今回は時間がなく未実施だが、10-20% の高速化は期待できる。

---

## 参考

- コミット
  - `21a36a7` データローダの.binリーダを並列化した。
  - `de44e42` KP特徴量とKP256学習パイプラインを追加した。
- 主要ファイル
  - `lib/nnue_training_data_stream.h` — `ParallelBinSfenInputStream` 定義
  - `training_data_loader.cpp` — `FeaturedBatchStream` (mutex 撤廃済み) と benchmark main
  - `CMakeLists.txt` — 常時 benchmark ビルド
  - `scripts/train/kp256.sh` — 本番起動スクリプト (実体は `scripts/train.py`)
  - `scripts/kp256/bench_workers.sh` — num_workers スイープ
  - `scripts/kp256/bench_batch.sh` — batch_size スイープ
  - `scripts/train/sitecustomize.py` — Cloudflare Access ヘッダ注入 (補助用途)
- 関連ログ
  - `scripts/kp256/logs/bench_workers.tsv` — worker スイープ結果
  - `scripts/kp256/logs/bench_batch.tsv` — batch スイープ結果
  - `runs/kp256_v1/lightning_logs/version_0/events.out.tfevents.*` — 本番 TensorBoard イベント
  - wandb: `https://wandb.tkgstrator.work/tkgstrator/nnue-pytorch/runs/ouibgh1y`
