"""Smoke tests for scripts and utilities.

GPU や学習データがなくても動作する範囲でテストする。
主に「import できるか」「引数パーサーが壊れていないか」「ヘルプが出るか」を検証。
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_script(script: str, args: list[str], *, expect_rc: int = 0) -> subprocess.CompletedProcess:
    """uv run python <script> <args> を実行して結果を返す。"""
    result = subprocess.run(
        ["uv", "run", "python", str(ROOT / script), *args],
        capture_output=True, text=True, timeout=30, cwd=ROOT,
    )
    assert result.returncode == expect_rc, (
        f"{script} exited with {result.returncode}, expected {expect_rc}\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    return result


# ---------------------------------------------------------------------------
# model パッケージの import テスト
# ---------------------------------------------------------------------------
class TestModelImports:
    def test_ranger21_import(self):
        from model import ranger21
        assert hasattr(ranger21, "Ranger21")

    def test_kp256_import(self):
        from model.kp256 import NNUEClassicModel, NNUEClassic
        assert NNUEClassicModel is not None
        assert NNUEClassic is not None

    def test_feature_sets_import(self):
        from model.features.blocks import KP, BucketHalfKP, MirrorBucketHalfKP
        assert KP is not None
        assert BucketHalfKP is not None
        assert MirrorBucketHalfKP is not None

    def test_feature_dimensions(self):
        from model.features.blocks import (
            BucketHalfKP, NUM_BHKP_FEATURES,
            MirrorBucketHalfKP, NUM_MBHKP_FEATURES,
            HalfKP, NUM_HKP_FEATURES,
        )
        _ = BucketHalfKP, MirrorBucketHalfKP, HalfKP

        assert NUM_BHKP_FEATURES == 13932, f"BucketHalfKP features: {NUM_BHKP_FEATURES}"
        assert NUM_MBHKP_FEATURES == 9288, f"MirrorBucketHalfKP features: {NUM_MBHKP_FEATURES}"
        assert NUM_HKP_FEATURES == 125388, f"HalfKP features: {NUM_HKP_FEATURES}"

    def test_half_kp_import(self):
        from model.features.blocks import HalfKP, NUM_HKP_FEATURES, HKP_HASH
        assert HalfKP is not None
        assert NUM_HKP_FEATURES == 125388
        # kHashValue = 0x5D69D5B9u ^ 1 (kFriend) = 0x5D69D5B8
        assert HKP_HASH == 0x5D69D5B8

    def test_serialize_classic_import(self):
        from model.utils.serialize_classic import NNUEClassicWriter
        assert NNUEClassicWriter is not None


# ---------------------------------------------------------------------------
# scripts/train.py — 学習ランチャー
# ---------------------------------------------------------------------------
class TestTrainRun:
    def test_help(self):
        r = run_script("scripts/train.py", ["--help"])
        assert "kp256" in r.stdout
        assert "hkp256" in r.stdout
        assert "-e EPOCHS" in r.stdout
        assert "-l LR" in r.stdout
        assert "-g GPUS" in r.stdout

    def test_missing_model_rejected(self):
        r = run_script("scripts/train.py", ["-g", "0"], expect_rc=2)
        assert "required" in r.stderr.lower()

    def test_invalid_model_rejected(self):
        r = run_script("scripts/train.py", ["-m", "invalid", "-g", "0"], expect_rc=2)
        assert "invalid choice" in r.stderr.lower()

    def test_missing_gpus_rejected(self):
        r = run_script("scripts/train.py", ["-m", "kp256"], expect_rc=2)
        assert "required" in r.stderr.lower()

    def test_model_configs(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from train import MODEL_CONFIGS, DEFAULTS
            assert "bkp256" not in MODEL_CONFIGS
            assert "mbkp256" not in MODEL_CONFIGS
            assert "kp256" in MODEL_CONFIGS
            assert "hkp256" in MODEL_CONFIGS
            assert "hkp768" in MODEL_CONFIGS
            assert MODEL_CONFIGS["kp256"]["features"] == "KP"
            assert MODEL_CONFIGS["hkp256"]["features"] == "HalfKP"
            assert MODEL_CONFIGS["hkp256"]["l1"] == 256
            assert MODEL_CONFIGS["hkp768"]["features"] == "HalfKP"
            assert MODEL_CONFIGS["hkp768"]["l1"] == 768
            assert DEFAULTS["epochs"] == 400
            assert DEFAULTS["lr"] == 3.5e-3
            assert DEFAULTS["save_steps"] == 6000
        finally:
            sys.path.pop(0)

    def test_build_training_namespace(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import argparse
            from train import build_training_namespace, MODEL_CONFIGS

            cli = argparse.Namespace(
                model="kp256", epochs=200, lr=1e-3, gpus="5",
                run_id="test", batch_size=32768, num_workers=64, gamma=0.99,
                lambda_=0.8, local=False,
                train_data="data/train.bin", val_data="data/val.bin",
                epoch_size=100_000_000, val_size=1_000_000,
                epochs_per_pass=20, val_fraction=1.0,
            )
            cli.save_steps = 15000
            cli.eval = False
            cli.eval_steps = 15000
            cli.val_steps = 500
            ns = build_training_namespace(cli, Path("/tmp/test"), "kp256_test", None)
            assert ns.features == "KP"
            assert ns.l1 == 256
            assert ns.max_epochs == 200
            assert ns.lr == 1e-3
            assert ns.batch_size == 32768
            assert ns.save_every_n_steps == 15000
            assert ns.resume_from_checkpoint is None
            # explicit epoch_size is passed through
            assert ns.epoch_size == 100_000_000
            assert ns.validation_size == 1_000_000
        finally:
            sys.path.pop(0)

    def test_build_training_namespace_epochs_per_pass(self):
        """epoch_size=None のとき epochs_per_pass から導出される。"""
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import argparse
            from train import build_training_namespace

            cli = argparse.Namespace(
                model="kp256", epochs=10, lr=3.5e-3, gpus="0",
                run_id="test", batch_size=65536, num_workers=4, gamma=0.992,
                lambda_=1.0, local=True,
                train_data="data/train.bin", val_data="data/val.bin",
                epoch_size=None, val_size=None,
                epochs_per_pass=10, val_fraction=1.0,
            )
            cli.save_steps = 7500
            cli.eval = False
            cli.eval_steps = 15000
            cli.val_steps = 500
            train_positions = 850_000_000  # 85M * 10
            val_positions   = 9_000_000
            epoch_size = int(train_positions / cli.epochs_per_pass)
            val_size   = int(val_positions * cli.val_fraction)
            ns = build_training_namespace(cli, Path("/tmp/test"), "kp256_test", None,
                                         epoch_size=epoch_size, val_size=val_size)
            assert ns.epoch_size == 85_000_000
            assert ns.validation_size == 9_000_000
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# scripts/train/env.py — 環境セットアップ
# ---------------------------------------------------------------------------
class TestTrainEnv:
    def test_root_path(self):
        sys.path.insert(0, str(ROOT / "scripts/train"))
        try:
            import env
            assert env.ROOT == ROOT
        finally:
            sys.path.pop(0)

    def test_dotenv_loading(self, tmp_path, monkeypatch):
        from scripts.utils import wandb_client
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_NNUE_VAR=hello123\n")
        monkeypatch.setattr(wandb_client, "ROOT", tmp_path)
        monkeypatch.delenv("TEST_NNUE_VAR", raising=False)
        wandb_client._load_dotenv()
        assert os.environ.get("TEST_NNUE_VAR") == "hello123"

    def test_dotenv_override_existing(self, tmp_path, monkeypatch):
        from scripts.utils import wandb_client
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_NNUE_VAR=from_dotenv\n")
        monkeypatch.setattr(wandb_client, "ROOT", tmp_path)
        monkeypatch.setenv("TEST_NNUE_VAR", "from_shell")
        wandb_client._load_dotenv()
        assert os.environ.get("TEST_NNUE_VAR") == "from_dotenv"

    def test_cf_headers_setup(self, monkeypatch):
        from scripts.utils import wandb_client
        monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "test-id")
        monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "test-secret")
        monkeypatch.delenv("WANDB__EXTRA_HTTP_HEADERS", raising=False)
        wandb_client._set_cf_headers_env()
        headers = json.loads(os.environ["WANDB__EXTRA_HTTP_HEADERS"])
        assert headers["CF-Access-Client-Id"] == "test-id"
        assert headers["CF-Access-Client-Secret"] == "test-secret"


# ---------------------------------------------------------------------------
# scripts/train/resume.py — レジューム判定
# ---------------------------------------------------------------------------
class TestResume:
    def test_no_ckpt_means_fresh(self, tmp_path):
        sys.path.insert(0, str(ROOT / "scripts/train"))
        try:
            from resume import plan_resume
            ckpt, status = plan_resume(tmp_path, "test-proj", "nonexistent-run")
            assert ckpt is None
            assert "missing" in status.lower() or "fresh" in status.lower()
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# scripts/train/*.sh — シェルラッパー
# ---------------------------------------------------------------------------
class TestShellWrappers:
    @pytest.mark.parametrize("script", ["kp256.sh"])
    def test_help_flag(self, script):
        r = subprocess.run(
            ["bash", str(ROOT / "scripts/train" / script), "--help"],
            capture_output=True, text=True, timeout=30, cwd=ROOT,
        )
        # --help は run.py に委譲される (exit 0)
        assert r.returncode == 0
        assert "kp256" in r.stdout


# ---------------------------------------------------------------------------
# scripts/utils/serialize.py — 変換ツール
# ---------------------------------------------------------------------------
class TestSerialize:
    def test_help(self):
        r = run_script("scripts/utils/serialize.py", ["--help"])
        assert "source" in r.stdout.lower()
        assert "--features" in r.stdout


# ---------------------------------------------------------------------------
# scripts/gauntlet/run_match.py — 対局ランナー
# ---------------------------------------------------------------------------
class TestRunMatch:
    def test_help(self):
        r = run_script("scripts/gauntlet/run_match.py", ["--help"])
        assert "--engine1" in r.stdout
        assert "--games" in r.stdout
        assert "--byoyomi" in r.stdout
        assert "--concurrency" in r.stdout

    def test_missing_args_rejected(self):
        r = run_script("scripts/gauntlet/run_match.py", [], expect_rc=2)
        assert "required" in r.stderr.lower()


# ---------------------------------------------------------------------------
# scripts/gauntlet/calc_rating.py — Elo 計算
# ---------------------------------------------------------------------------
class TestCalcRating:
    def test_basic_calculation(self):
        r = run_script("scripts/gauntlet/calc_rating.py", ["55", "45"])
        assert "55.0" in r.stdout


# ---------------------------------------------------------------------------
# scripts/model_eval/ — 評価ユーティリティ
# ---------------------------------------------------------------------------
class TestModelEval:
    def test_ckpt_info_help(self):
        r = run_script("scripts/model_eval/ckpt_info.py", ["--help"])
        assert "--shell" in r.stdout

    def test_pgn_elo_help(self):
        r = run_script("scripts/model_eval/pgn_elo.py", ["--help"])
        assert "--pgn" in r.stdout
        assert "--name" in r.stdout

    def test_pgn_elo_with_fixture(self, tmp_path):
        pgn = tmp_path / "test.pgn"
        pgn.write_text(textwrap.dedent("""\
            [White "modelA"]
            [Black "modelB"]
            [Result "1-0"]

            1-0

            [White "modelB"]
            [Black "modelA"]
            [Result "0-1"]

            0-1

            [White "modelA"]
            [Black "modelB"]
            [Result "1/2-1/2"]

            1/2-1/2
        """))
        r = run_script("scripts/model_eval/pgn_elo.py", ["--pgn", str(pgn), "--name", "modelA"])
        data = json.loads(r.stdout.strip())
        assert data["wins"] == 2
        assert data["losses"] == 0
        assert data["draws"] == 1

    def test_compute_report_help(self):
        r = run_script("scripts/model_eval/compute_report.py", ["--help"])
        assert "--out-json" in r.stdout or "--out-md" in r.stdout


# ---------------------------------------------------------------------------
# scripts/utils/ — ユーティリティ (import テスト)
# ---------------------------------------------------------------------------
class TestUtilsImport:
    def test_ftperm_importable(self):
        chess = pytest.importorskip("chess", reason="chess not installed")
        sys.path.insert(0, str(ROOT / "scripts/utils"))
        try:
            import ftperm
            assert ftperm is not None
        finally:
            sys.path.pop(0)

    def test_delete_bad_nets_importable(self):
        sys.path.insert(0, str(ROOT / "scripts/utils"))
        try:
            import delete_bad_nets
            assert delete_bad_nets is not None
        finally:
            sys.path.pop(0)

    def test_do_plots_help(self):
        r = run_script("scripts/utils/do_plots.py", ["--help"])
        assert r.returncode == 0
