"""Regression for the delayed-response oracle; no database/browser required."""

import subprocess
from pathlib import Path


def test_transcript_gate_settles_success_aborted_and_invalid_bodies():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["node", str(root / "tests/js/transcript-gate.cjs"), str(root / "tests/e2e/transcript-gate.js")],
        check=True,
        timeout=10,
    )
