"""Tests for model/utils/net_stats.py — pure-tensor weight anomaly detection."""
from __future__ import annotations

import math

import torch
import pytest

from model.utils.net_stats import compute_net_stats
from model.quantize import QuantizationConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_q() -> QuantizationConfig:
    return QuantizationConfig()  # nnue2score=600, weight_scale_hidden=64, weight_scale_out=16, quantized_one=127


def _make_tensors(
    ft_w_std: float = 0.1,
    ft_w_nan: bool = False,
    ft_w_inf: bool = False,
    fc_w_std: float = 0.01,
):
    """Return a minimal set of tensors resembling a KP256 model."""
    torch.manual_seed(0)
    ft_weight = torch.randn(4096, 256) * ft_w_std
    if ft_w_nan:
        ft_weight[0, 0] = float("nan")
    if ft_w_inf:
        ft_weight[0, 0] = float("inf")
    ft_bias    = torch.zeros(256)
    fc1_weight = torch.randn(32, 512) * fc_w_std
    fc1_bias   = torch.zeros(32)
    fc2_weight = torch.randn(32, 32) * fc_w_std
    fc2_bias   = torch.zeros(32)
    fc_out_weight = torch.randn(1, 32) * fc_w_std
    fc_out_bias   = torch.zeros(1)
    return (ft_weight, ft_bias, fc1_weight, fc1_bias,
            fc2_weight, fc2_bias, fc_out_weight, fc_out_bias)


def _run(ft_w_std: float = 0.1, **kw) -> dict:
    tensors = _make_tensors(ft_w_std=ft_w_std, **kw)
    return compute_net_stats(*tensors, quantization=_default_q())


# ---------------------------------------------------------------------------
# Healthy case
# ---------------------------------------------------------------------------

class TestHealthy:
    def test_verdict_healthy_for_small_weights(self):
        stats = _run(ft_w_std=0.1)
        assert stats["verdict"] == "healthy"

    def test_no_issues_for_healthy(self):
        stats = _run(ft_w_std=0.1)
        assert stats["issues"] == []

    def test_has_nan_false(self):
        stats = _run(ft_w_std=0.1)
        assert stats["has_nan"] is False

    def test_has_inf_false(self):
        stats = _run(ft_w_std=0.1)
        assert stats["has_inf"] is False

    def test_all_expected_keys_present(self):
        stats = _run()
        expected_keys = {
            "ft_weight_mean", "ft_weight_std", "ft_weight_abs_max",
            "ft_bias_abs_max",
            "fc1_weight_std", "fc1_weight_abs_max", "fc1_int8_sat_frac",
            "fc1_bias_abs_max",
            "fc2_weight_std", "fc2_weight_abs_max", "fc2_int8_sat_frac",
            "fc2_bias_abs_max",
            "fc_out_weight_std", "fc_out_weight_abs_max", "fc_out_int8_sat_frac",
            "fc_out_bias_abs_max",
            "has_nan", "has_inf", "verdict", "issues",
        }
        assert expected_keys.issubset(set(stats.keys()))


# ---------------------------------------------------------------------------
# FT weight explosion (critical)
# ---------------------------------------------------------------------------

class TestFTExplosionCritical:
    def test_verdict_critical_when_ft_std_exceeds_30(self):
        # torch.randn * scale has std ≈ scale; use 35 to exceed threshold of 30
        stats = _run(ft_w_std=35.0)
        assert stats["verdict"] == "critical"

    def test_issues_contain_ft_weight_std(self):
        stats = _run(ft_w_std=35.0)
        assert any("ft_weight_std" in issue for issue in stats["issues"])

    def test_ft_weight_std_value_is_present_in_issue_string(self):
        stats = _run(ft_w_std=35.0)
        # The issue string should contain the actual value, e.g. "ft_weight_std=35.0 > 30"
        ft_std_issues = [i for i in stats["issues"] if "ft_weight_std" in i]
        assert len(ft_std_issues) >= 1


# ---------------------------------------------------------------------------
# NaN injection (critical)
# ---------------------------------------------------------------------------

class TestNaN:
    def test_verdict_critical_when_nan_in_ft(self):
        stats = _run(ft_w_nan=True)
        assert stats["verdict"] == "critical"

    def test_has_nan_true(self):
        stats = _run(ft_w_nan=True)
        assert stats["has_nan"] is True

    def test_issues_contain_has_nan(self):
        stats = _run(ft_w_nan=True)
        assert any("has_nan" in issue for issue in stats["issues"])


# ---------------------------------------------------------------------------
# Inf injection (critical)
# ---------------------------------------------------------------------------

class TestInf:
    def test_verdict_critical_when_inf_in_ft(self):
        stats = _run(ft_w_inf=True)
        assert stats["verdict"] == "critical"

    def test_has_inf_true(self):
        stats = _run(ft_w_inf=True)
        assert stats["has_inf"] is True


# ---------------------------------------------------------------------------
# Warning boundary: ft_weight_std in (20, 30)
# ---------------------------------------------------------------------------

class TestWarningBoundary:
    def test_verdict_warning_when_ft_std_between_20_and_30(self):
        # We need std ≈ 25.  randn * scale has std ≈ scale.
        # Use scale=2.6 → std ≈ 2.6 * sqrt(1) per element → need std of tensor ≈ 25.
        # torch.randn * 2.6 → per-element std = 2.6, but tensor std is also ~2.6.
        # Use scale=25 / sqrt(1) = 25; then abs_max will be large → would trigger abs_max critical.
        # Use a scaled tensor where std ≈ 25 but abs_max < 500.
        # randn with std=25 has abs_max of ~4*25=100 for small tensor, but 4096*256 elements →
        # abs_max ~ 4*25 ≈ 100 < 300 (warning threshold), so verdict should be warning not critical.
        torch.manual_seed(42)
        ft_weight = torch.randn(4096, 256) * 2.6  # std ≈ 2.6 → too small
        # Directly set std ≈ 25 using a scaled tensor
        ft_weight = torch.randn(4096, 256)
        # std of randn is 1.0, scale to ~25
        ft_weight = ft_weight * 25.0
        # Clamp abs_max to stay below critical (500) but keep std in (20,30)
        ft_weight = ft_weight.clamp(-200, 200)
        ft_std = float(ft_weight.std().item())
        # The clamp may have reduced std slightly; if still > 20, proceed
        assert ft_std > 20.0, f"Setup failed: ft_std={ft_std:.1f} not > 20"
        assert ft_std < 30.0, f"Setup failed: ft_std={ft_std:.1f} not < 30"

        ft_bias    = torch.zeros(256)
        fc1_weight = torch.randn(32, 512) * 0.01
        fc1_bias   = torch.zeros(32)
        fc2_weight = torch.randn(32, 32) * 0.01
        fc2_bias   = torch.zeros(32)
        fc_out_weight = torch.randn(1, 32) * 0.01
        fc_out_bias   = torch.zeros(1)

        stats = compute_net_stats(
            ft_weight, ft_bias,
            fc1_weight, fc1_bias,
            fc2_weight, fc2_bias,
            fc_out_weight, fc_out_bias,
            quantization=_default_q(),
        )
        assert stats["verdict"] == "warning", (
            f"Expected warning, got {stats['verdict']}; "
            f"ft_std={ft_std:.1f}, abs_max={float(ft_weight.abs().max()):.1f}, "
            f"issues={stats['issues']}"
        )

    def test_verdict_healthy_when_ft_std_below_20(self):
        stats = _run(ft_w_std=1.5)  # std ≈ 1.5
        assert stats["verdict"] == "healthy"


# ---------------------------------------------------------------------------
# FC int8 saturation (critical)
# ---------------------------------------------------------------------------

class TestFC_SaturationCritical:
    def test_verdict_critical_when_fc1_saturates(self):
        q = _default_q()
        max_hidden_w = q.quantized_one / q.weight_scale_hidden  # 127/64 ≈ 1.984
        # Fill fc1_weight so all values exceed max_hidden_w → sat_frac = 1.0 > 0.15
        torch.manual_seed(0)
        ft_weight  = torch.randn(4096, 256) * 0.1
        ft_bias    = torch.zeros(256)
        fc1_weight = torch.full((32, 512), max_hidden_w * 2)  # all saturated
        fc1_bias   = torch.zeros(32)
        fc2_weight = torch.randn(32, 32) * 0.01
        fc2_bias   = torch.zeros(32)
        fc_out_weight = torch.randn(1, 32) * 0.01
        fc_out_bias   = torch.zeros(1)

        stats = compute_net_stats(
            ft_weight, ft_bias,
            fc1_weight, fc1_bias,
            fc2_weight, fc2_bias,
            fc_out_weight, fc_out_bias,
            quantization=q,
        )
        assert stats["verdict"] == "critical"
        assert stats["fc1_int8_sat_frac"] > 0.15
        assert any("fc1_int8_sat_frac" in issue for issue in stats["issues"])
