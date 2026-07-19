"""PythonTarget — import and call a Python agent harness (REQ-TA-2).

    costbomb run --target ./agent.py:handler

The handler receives the input text and returns what it spent — a ``Trace`` (if it
already emits the OTel GenAI profile) or a ``RunRecord`` (the honest usage-field
contract). costbomb meters the result; nothing about the provider is assumed.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.targets.base import TargetContext, coerce_trace


def _load_handler(spec: str) -> Callable[..., Any]:
    """Resolve ``module:func`` or ``./path/to/file.py:func`` to a callable."""
    if ":" not in spec:
        raise ValueError(f"target spec must be 'module:func' or 'file.py:func', got {spec!r}")
    mod_part, func_name = spec.rsplit(":", 1)
    if mod_part.endswith(".py") or "/" in mod_part:
        path = Path(mod_part).resolve()
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot import {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(mod_part)
    return getattr(module, func_name)


class PythonTarget:
    def __init__(
        self,
        handler: str | Callable[..., Any],
        *,
        capabilities: TargetCapabilities | None = None,
    ) -> None:
        self._handler = _load_handler(handler) if isinstance(handler, str) else handler
        self._caps = capabilities or TargetCapabilities()

    def capabilities(self) -> TargetCapabilities:
        return self._caps

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        try:
            result = self._handler(input.text, ctx)
        except TypeError:
            result = self._handler(input.text)
        return coerce_trace(result, seed=ctx.seed, attack_class=input.attack_class)
