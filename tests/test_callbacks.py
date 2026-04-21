"""Tests for scripts/train/callbacks.py — ModelEvalCallback async behaviour."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "train"))

from callbacks import ModelEvalCallback, TimeLimitAfterCheckpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trainer(global_step: int = 0) -> SimpleNamespace:
    """Minimal trainer-like object."""
    ns = SimpleNamespace(global_step=global_step)
    ns.save_checkpoint = MagicMock()
    return ns


def _make_pl_module() -> SimpleNamespace:
    """Minimal pl_module-like object with a .model attribute."""
    ns = SimpleNamespace(model=SimpleNamespace())
    ns.log = MagicMock()
    return ns


# ---------------------------------------------------------------------------
# step gating
# ---------------------------------------------------------------------------

class TestStepGating:
    def test_skips_step_zero(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1000)
        trainer = _make_trainer(global_step=0)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        cb.on_fit_end(trainer, pl_module)

        trainer.save_checkpoint.assert_not_called()

    def test_runs_at_first_multiple(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1000)
        trainer = _make_trainer(global_step=1000)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        time.sleep(0.1)
        cb.on_fit_end(trainer, pl_module)

        trainer.save_checkpoint.assert_called_once()

    @pytest.mark.parametrize("step", [1, 500, 999])
    def test_skips_before_first_multiple(self, step):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1000)
        trainer = _make_trainer(global_step=step)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        cb.on_fit_end(trainer, pl_module)

        trainer.save_checkpoint.assert_not_called()

    def test_skips_duplicate_calls_at_same_step(self):
        """Same global_step called twice should fire at most once."""
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1000)
        trainer = _make_trainer(global_step=1000)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        time.sleep(0.1)
        cb.on_fit_end(trainer, pl_module)

        trainer.save_checkpoint.assert_called_once()

    def test_runs_again_after_interval(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1000)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer := _make_trainer(global_step=1000), pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        trainer.global_step = 2000
        cb.on_validation_epoch_end(trainer, pl_module)
        time.sleep(0.1)
        cb.on_fit_end(trainer, pl_module)

        assert trainer.save_checkpoint.call_count == 2


# ---------------------------------------------------------------------------
# async (non-blocking) behaviour
# ---------------------------------------------------------------------------

class TestAsyncEval:
    def test_on_validation_epoch_end_returns_immediately(self):
        """on_validation_epoch_end should not block on the eval subprocess."""
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1)
        trainer = _make_trainer(global_step=1)
        pl_module = _make_pl_module()

        # Make _do_balance slow.
        original = cb._do_balance
        cb._do_balance = lambda path: time.sleep(5)

        cb.on_fit_start(trainer, pl_module)

        start = time.monotonic()
        cb.on_validation_epoch_end(trainer, pl_module)
        elapsed = time.monotonic() - start

        cb.on_fit_end(trainer, pl_module)

        assert elapsed < 2.0, f"on_validation_epoch_end blocked for {elapsed:.1f}s"

    def test_worker_thread_is_daemon(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test")
        trainer = _make_trainer()
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        assert cb._worker is not None
        assert cb._worker.daemon is True
        cb.on_fit_end(trainer, pl_module)


# ---------------------------------------------------------------------------
# pending replacement (no backlog)
# ---------------------------------------------------------------------------

class TestPendingReplacement:
    def test_old_pending_is_discarded(self):
        """When eval is slow and new intervals arrive, only the latest is kept."""
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1)

        # Block the worker so it never picks up work.
        gate = threading.Event()
        original_loop = cb._worker_loop

        def blocked_loop():
            gate.wait()
            original_loop()

        trainer = _make_trainer(global_step=1)
        pl_module = _make_pl_module()

        cb.on_fit_start(trainer, pl_module)
        # Replace worker with a blocked one.
        cb._stop.set()
        cb._new_work.set()
        cb._worker.join(timeout=5)
        cb._stop.clear()
        cb._worker = threading.Thread(target=blocked_loop, daemon=True)
        cb._worker.start()

        # Submit two intervals while worker is blocked.
        cb.on_validation_epoch_end(trainer, pl_module)
        first_pending = cb._pending

        trainer2 = _make_trainer(global_step=2)
        trainer2.save_checkpoint = MagicMock()
        cb.on_validation_epoch_end(trainer2, pl_module)

        # Only the latest pending should survive.
        assert cb._pending is not None
        assert cb._pending is not first_pending

        gate.set()
        cb._stop.set()
        cb._new_work.set()
        cb._worker.join(timeout=5)


# ---------------------------------------------------------------------------
# result flushing
# ---------------------------------------------------------------------------

class TestResultFlushing:
    def test_results_logged_on_next_epoch(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1)
        trainer = _make_trainer(global_step=1)
        pl_module = _make_pl_module()

        # Inject results as if the background worker produced them.
        cb._results = {"eval/balanced_mean": 42.0, "eval/balanced_std": 3.14}

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)
        cb.on_fit_end(trainer, pl_module)

        # Results should have been flushed via pl_module.log().
        calls = {c.args[0]: c.args[1] for c in pl_module.log.call_args_list}
        assert calls["eval/balanced_mean"] == 42.0
        assert calls["eval/balanced_std"] == 3.14

    def test_results_cleared_after_flush(self):
        cb = ModelEvalCallback(features="KP", l1=256, run_name="test", every_n_steps=1)
        trainer = _make_trainer(global_step=1)
        pl_module = _make_pl_module()

        cb._results = {"eval/balanced_mean": 1.0}

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_epoch_end(trainer, pl_module)

        assert cb._results == {}
        cb.on_fit_end(trainer, pl_module)


# ---------------------------------------------------------------------------
# TimeLimitAfterCheckpoint
# ---------------------------------------------------------------------------

class TestTimeLimitAfterCheckpoint:
    def test_parse_valid_format(self):
        cb = TimeLimitAfterCheckpoint("00:01:30:00")
        assert cb.max_duration == 5400.0

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError):
            TimeLimitAfterCheckpoint("01:30:00")

    def test_does_not_stop_before_limit(self):
        cb = TimeLimitAfterCheckpoint("00:01:00:00")
        trainer = SimpleNamespace(should_stop=False)
        pl_module = SimpleNamespace()

        cb.on_fit_start(trainer, pl_module)
        cb.on_validation_end(trainer, pl_module)

        assert trainer.should_stop is False

    def test_stops_after_limit(self):
        cb = TimeLimitAfterCheckpoint("00:00:00:00")
        trainer = SimpleNamespace(should_stop=False)
        pl_module = SimpleNamespace()

        cb.on_fit_start(trainer, pl_module)
        time.sleep(0.01)
        cb.on_validation_end(trainer, pl_module)

        assert trainer.should_stop is True
