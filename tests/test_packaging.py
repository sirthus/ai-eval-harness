"""Packaging regressions for non-editable installs."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_includes_prompt_templates(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    generated_paths = [
        repo_root / "build",
        repo_root / "src" / "harness.egg-info",
    ]
    existed_before = {path: path.exists() for path in generated_paths}

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(tmp_path),
                str(repo_root),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        for path in generated_paths:
            if not existed_before[path] and path.exists():
                shutil.rmtree(path)

    wheels = list(tmp_path.glob("harness-*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    assert {
        "harness/prompts/v1.txt",
        "harness/prompts/v2.txt",
        "harness/prompts/v3.txt",
        "harness/prompts/judge_v1.txt",
    }.issubset(names)
