"""ProxyTarget — meter a real agent with zero instrumentation (REQ-CM-5c).

The fuzzer drives the agent through whatever entry point it already exposes (an
in-process call, an HTTP request, an MCP tool); meanwhile the agent's LLM traffic
flows through a :class:`~costbomb.proxy.ProxyMeter`, which records real usage. This
target simply *brackets* one driven input as one metered run:

    proxy.start_run() → driver(input) runs the agent → proxy.finish_run() → Trace

No ``RunRecord``, no handler rewrite — the agent only had its model ``base_url``
pointed at the proxy. Use this for framework / SDK-direct agents invoked in-process
(the ProxyMeter is shared); the forwarding server (``costbomb proxy``) covers agents
in a separate process.
"""

from __future__ import annotations

from collections.abc import Callable

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.proxy import ProxyMeter
from costbomb.targets.base import TargetContext

Driver = Callable[[str, TargetContext], object]


class ProxyTarget:
    def __init__(
        self,
        driver: Driver,
        proxy: ProxyMeter,
        *,
        capabilities: TargetCapabilities | None = None,
    ) -> None:
        self._driver = driver
        self.proxy = proxy
        self._caps = capabilities or TargetCapabilities(
            has_tools=True, can_spawn=True, accepts_documents=True
        )

    def capabilities(self) -> TargetCapabilities:
        return self._caps

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        self.proxy.start_run(attack_class=input.attack_class)
        self._driver(input.text, ctx)  # agent runs; its model calls are recorded live
        return self.proxy.finish_run()
