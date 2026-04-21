import sys
from pathlib import Path

# テスト実行時にプロジェクトルートを sys.path に追加し、
# model, data_loader 等のパッケージを import 可能にする。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
