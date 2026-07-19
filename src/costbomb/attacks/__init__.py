"""Attack library — importing this package populates the registry (REQ-AL-4).

    from costbomb.attacks import registry
    registry.names()   # ['clarification-trap', 'context-bomb', 'recursion', ...]

The five SPEC classes register on import here. Community/⊕ classes register the same
way (v0.2 ``v02.py``); external classes load via entry points without forking core.
"""

from __future__ import annotations

from costbomb.attacks.base import (
    AttackClass,
    AttackRegistry,
    BaseAttack,
    Input,
    Mutator,
    TargetCapabilities,
    registry,
)
from costbomb.attacks.v01 import register_all as _register_v01
from costbomb.attacks.v02 import register_all as _register_v02

_register_v01()
_register_v02()

__all__ = [
    "AttackClass",
    "AttackRegistry",
    "BaseAttack",
    "Input",
    "Mutator",
    "TargetCapabilities",
    "registry",
]
