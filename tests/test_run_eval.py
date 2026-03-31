"""Tests for git metadata helpers in run_eval."""

from __future__ import annotations

import subprocess

from harness.run_eval import _git_commit_hash, _git_is_dirty


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
