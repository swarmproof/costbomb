"""Target adapters — the embedded/standalone seam (ADR-3)."""

from __future__ import annotations

from costbomb.targets.base import (
    ModelCall,
    RunRecord,
    Target,
    TargetContext,
    coerce_trace,
)
from costbomb.targets.fake import FakeTarget
from costbomb.targets.http_target import HTTPTarget
from costbomb.targets.persona_target import PersonaTarget
from costbomb.targets.python_target import PythonTarget

__all__ = [
    "FakeTarget",
    "HTTPTarget",
    "ModelCall",
    "PersonaTarget",
    "PythonTarget",
    "RunRecord",
    "Target",
    "TargetContext",
    "coerce_trace",
]
