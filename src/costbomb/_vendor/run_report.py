"""RunReport contract — the shared report model costbomb populates (REQ-RP-2).

VENDORED shape of the relevant slice of ``stampede/observer/report.py``. costbomb
owns **no renderer**: it produces an economic-findings fragment that slots into the
``RunReport.adversarial`` section, and both the embedded (Agent Readiness Report)
and standalone paths render from the identical model (ARCHITECTURE §5.1).

Only the keys costbomb reads or writes are mirrored here. The full model lives in
stampede; when it is published as a package this module is dropped for that import.
"""

from __future__ import annotations

from typing import Any

# Keys stampede's `RunReport.adversarial` dict already carries (report.py). costbomb
# augments this dict rather than inventing a sibling section, so the denial-of-wallet
# story renders in the existing adversarial block.
ADVERSARIAL_KEYS = (
    "cohort_size",
    "injection_probes",
    "destructive_reached",
    "denial_of_wallet_flags",
)


def merge_economic_section(adversarial: dict[str, Any], economic: dict[str, Any]) -> dict[str, Any]:
    """Merge costbomb's ``economic`` fragment into a ``RunReport.adversarial`` dict.

    Non-destructive: stampede's own adversarial keys are preserved; costbomb adds an
    ``economic`` sub-object and bumps ``denial_of_wallet_flags`` to the number of
    findings it confirmed. Returns a new dict (deterministic key order for golden
    snapshots, NFR-2).
    """
    merged = dict(adversarial)
    merged["economic"] = economic
    merged["denial_of_wallet_flags"] = max(
        int(merged.get("denial_of_wallet_flags", 0)),
        len(economic.get("findings", [])),
    )
    return dict(sorted(merged.items()))
