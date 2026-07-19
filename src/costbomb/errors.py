"""Shared exception types."""

from __future__ import annotations


class CostbombError(Exception):
    """Base for all costbomb errors."""


class SideEffectError(CostbombError):
    """Raised when a run would hit a real side-effecting system without opt-in.

    NFR-5 / ADR-5: the default target is side-effect-free (mockworld/dry). Hitting a
    real endpoint requires an explicit ``--allow-side-effects`` because fuzzing for
    maximum tool calls could otherwise fire real charges or emails.
    """


class BudgetExceededError(CostbombError):
    """Raised if a single confirmation run would breach the own-budget cap (NFR-1)."""
