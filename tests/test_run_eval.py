"""Tests for git metadata helpers in run_eval."""

from __future__ import annotations

import subprocess

from harness.run_eval import _compute_quality_gate, _git_commit_hash, _git_is_dirty


class TestGitCommitHash:
    def test_returns_short_hash(self, mocker):
        mocker.patch(
            "harness.run_eval.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--short", "HEAD"],
                returncode=0,
                stdout="abc1234\n",
            ),
        )

        assert _git_commit_hash() == "abc1234"

    def test_returns_unknown_and_logs_warning_on_subprocess_failure(self, mocker, caplog):
        mocker.patch(
            "harness.run_eval.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )

        with caplog.at_level("WARNING"):
            assert _git_commit_hash() == "unknown"

        assert "Failed to determine git commit hash" in caplog.text


class TestGitIsDirty:
    def test_returns_false_for_clean_worktree(self, mocker):
        mocker.patch(
            "harness.run_eval.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout="",
            ),
        )

        assert _git_is_dirty() is False

    def test_returns_true_for_dirty_worktree(self, mocker):
        mocker.patch(
            "harness.run_eval.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M src/harness/run_eval.py\n",
            ),
        )

        assert _git_is_dirty() is True

    def test_returns_true_and_logs_warning_on_subprocess_failure(self, mocker, caplog):
        mocker.patch(
            "harness.run_eval.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["git", "status", "--porcelain"]),
        )

        with caplog.at_level("WARNING"):
            assert _git_is_dirty() is True

        assert "Failed to determine git dirty state" in caplog.text


class TestComputeQualityGate:
    def test_high_pass_rate_no_issues_returns_pass(self):
        assert _compute_quality_gate(pass_rate=0.70, borderlines=0, parse_failures=0) == "pass"

    def test_low_pass_rate_returns_fail(self):
        assert _compute_quality_gate(pass_rate=0.39, borderlines=0, parse_failures=0) == "fail"

    def test_mid_pass_rate_no_borderlines_no_failures_returns_needs_review(self):
        # 40-69% pass rate with no borderlines and no parse failures should be needs_review,
        # not good enough to pass outright but not bad enough to fail.
        assert _compute_quality_gate(pass_rate=0.55, borderlines=0, parse_failures=0) == "needs_review"

    def test_good_pass_rate_with_borderlines_returns_needs_review(self):
        assert _compute_quality_gate(pass_rate=0.80, borderlines=3, parse_failures=0) == "needs_review"

    def test_good_pass_rate_with_parse_failures_returns_needs_review(self):
        assert _compute_quality_gate(pass_rate=0.80, borderlines=0, parse_failures=1) == "needs_review"
