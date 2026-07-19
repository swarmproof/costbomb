"""costbomb — denial-of-wallet fuzzing for agent systems.

A directed greybox fuzzer whose fitness function is dollars. It hunts the inputs
that make an agent spend $500 to answer a $0.05 question, ranks the worst offenders
with exact reproduction, and gates CI on spend regressions.

Public surface (the standalone-extract API, ARCHITECTURE §6):

    from costbomb import CostMeter, PriceTable, FuzzEngine, FakeTarget, run

Everything is organized around one invariant: **the cost meter is the oracle**
(ADR-2). The attack library proposes, the engine searches, the reporter gates —
all optimizing against the number the meter produces.
"""

from __future__ import annotations

from costbomb.attacks.base import AttackClass, Input, TargetCapabilities, registry
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.findings import Finding, RunFindings
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import Target, TargetContext
from costbomb.targets.fake import FakeTarget

__version__ = "0.2.0.dev0"

__all__ = [
    "AttackClass",
    "CostMeter",
    "FakeTarget",
    "Finding",
    "FuzzEngine",
    "Input",
    "PriceTable",
    "RunFindings",
    "SearchConfig",
    "Target",
    "TargetCapabilities",
    "TargetContext",
    "__version__",
    "registry",
]
