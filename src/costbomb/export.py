"""Exports — machine-readable findings + the OTel GenAI-profile trace (REQ-RP-5).

Findings export to ``findings.json`` (a stable schema for CI/tools). The traces
export as OTel GenAI-profile spans (``gen_ai.*`` + ``swarmproof.*`` attributes) so a
finding imports natively into Langfuse or any OTel GenAI backend — no bespoke schema
(NFR-9). The span dicts *are* the profile; no translation needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from costbomb.findings import RunFindings


def findings_json(rf: RunFindings) -> dict[str, Any]:
    return rf.to_findings_json()


def otel_spans(rf: RunFindings) -> dict[str, Any]:
    """All worst-case traces as OTel GenAI-profile spans, grouped by finding."""
    out: list[dict[str, Any]] = []
    for f in rf.findings:
        if f.worst_trace is None:
            continue
        out.append(
            {
                "attack_class": f.attack_class,
                "worst_usd": round(f.worst_usd, 6),
                "trace": f.worst_trace.to_dict(),
            }
        )
    return {"run_id": rf.run_id, "seed": rf.seed, "traces": out}


def write_findings_json(rf: RunFindings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(findings_json(rf), indent=2, sort_keys=True) + "\n")


def write_otel_json(rf: RunFindings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(otel_spans(rf), indent=2, sort_keys=True) + "\n")
