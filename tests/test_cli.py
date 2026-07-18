"""CLI surface (TEST-PLAN §5 E2E-6, REQ-CI-1/4)."""

from __future__ import annotations

from typer.testing import CliRunner

from costbomb.cli import app

runner = CliRunner()


def test_run_dry_run_exits_zero_and_reports() -> None:
    result = runner.invoke(app, ["run", "--target", "fake", "--dry-run"])
    assert result.exit_code == 0
    assert "amplification" in result.stdout


def test_run_budget_breach_exits_nonzero() -> None:
    # Tiny budget → worst-case exceeds it → gate fails → non-zero exit (REQ-CI-1).
    result = runner.invoke(app, ["run", "--target", "fake", "--budget", "0.0001", "--max-spend", "1.0"])
    assert result.exit_code == 1
    assert "gate failed" in result.stdout


def test_attacks_lists_classes() -> None:
    result = runner.invoke(app, ["attacks"])
    assert result.exit_code == 0
    for name in ("retry-loop", "tool-storm", "context-bomb", "recursion", "clarification-trap"):
        assert name in result.stdout


def test_price_shows_table() -> None:
    result = runner.invoke(app, ["price"])
    assert result.exit_code == 0
    assert "2026-07-13" in result.stdout


def test_baseline_update_and_gate_roundtrip(tmp_path) -> None:
    base = tmp_path / ".costbomb-baseline.json"
    up = runner.invoke(app, ["baseline", "update", "--target", "fake", "--baseline", str(base)])
    assert up.exit_code == 0 and base.exists()

    # Same seed/target vs its own baseline → gate green.
    g = runner.invoke(app, ["run", "--target", "fake", "--fail-on-regression", "--baseline", str(base)])
    assert g.exit_code == 0
    assert "gate passed" in g.stdout
