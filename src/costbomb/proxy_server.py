"""Forwarding proxy server — meter an out-of-process agent (REQ-CM-5c).

A thin HTTP shell around :class:`~costbomb.proxy.ProxyMeter`. Point your agent's model
``base_url`` at it; it forwards every request to the real upstream, reads the
response ``usage``, and records it against the run named by the ``x-costbomb-run``
header. The fuzzer brackets a run with two control calls:

    POST /costbomb/run/start   {"run_id": "...", "attack_class": "retry-loop"}
    ... agent makes model calls carrying header  x-costbomb-run: <run_id> ...
    POST /costbomb/run/finish  {"run_id": "..."}   → returns the metered Trace JSON

All the dollar logic lives in ``ProxyMeter``; :func:`proxy_handle` is a pure function
(inject ``forward``) so the routing/correlation is unit-testable without a socket.
"""

from __future__ import annotations

import contextlib
import json
import urllib.request
from collections.abc import Callable
from typing import Any

from costbomb.pricing import PriceTable
from costbomb.proxy import ProxyMeter

# forward(method, url, headers, body) -> (status, response_headers, response_body_bytes)
Forward = Callable[[str, str, dict[str, str], bytes], "tuple[int, dict[str, str], bytes]"]

CONTROL_START = "/costbomb/run/start"
CONTROL_FINISH = "/costbomb/run/finish"
RUN_HEADER = "x-costbomb-run"


class RunStore:
    """Keeps one :class:`ProxyMeter` per active run id (server-mode correlation)."""

    def __init__(self, prices: PriceTable) -> None:
        self.prices = prices
        self._runs: dict[str, ProxyMeter] = {}

    def start(self, run_id: str, *, attack_class: str = "") -> None:
        pm = ProxyMeter(self.prices, run_id=run_id)
        pm.start_run(attack_class=attack_class)
        self._runs[run_id] = pm

    def record(self, run_id: str, response: dict[str, Any]) -> None:
        pm = self._runs.get(run_id)
        if pm is not None:
            pm.record(response)

    def finish(self, run_id: str) -> dict[str, Any] | None:
        pm = self._runs.pop(run_id, None)
        if pm is None:
            return None
        trace = pm.finish_run()
        bd = pm.cost(trace)
        return {"trace": trace.to_dict(), "total_usd": round(bd.total_usd, 8)}

    @property
    def active(self) -> int:
        return len(self._runs)


def _default_forward(method: str, url: str, headers: dict[str, str], body: bytes):  # pragma: no cover - network
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - upstream is operator-configured
        return resp.status, dict(resp.headers), resp.read()


def proxy_handle(
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    *,
    upstream: str,
    store: RunStore,
    forward: Forward,
) -> tuple[int, dict[str, str], bytes]:
    """Route one request. Control paths bracket runs; everything else forwards + meters."""
    lower = {k.lower(): v for k, v in headers.items()}

    if path == CONTROL_START and method == "POST":
        payload = json.loads(body or b"{}")
        store.start(payload["run_id"], attack_class=payload.get("attack_class", ""))
        return _json(200, {"ok": True})

    if path == CONTROL_FINISH and method == "POST":
        payload = json.loads(body or b"{}")
        result = store.finish(payload["run_id"])
        if result is None:
            return _json(404, {"error": "unknown run_id"})
        return _json(200, result)

    # --- forward to the real upstream, then meter the response ---
    status, resp_headers, resp_body = forward(method, upstream.rstrip("/") + path, headers, body)
    run_id = lower.get(RUN_HEADER)
    if run_id:
        # non-JSON / streaming responses aren't metered; forwarded untouched
        with contextlib.suppress(ValueError, KeyError):
            store.record(run_id, json.loads(resp_body))
    return status, resp_headers, resp_body


def _json(status: int, obj: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(obj).encode()
    return status, {"content-type": "application/json"}, body


def run_server(*, upstream: str, port: int, prices: PriceTable) -> None:  # pragma: no cover - socket loop
    """Start the blocking forwarding server (stdlib; no extra deps)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    store = RunStore(prices)

    class Handler(BaseHTTPRequestHandler):
        def _do(self, method: str) -> None:
            length = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            status, resp_headers, resp_body = proxy_handle(
                method, self.path, dict(self.headers), body,
                upstream=upstream, store=store, forward=_default_forward,
            )
            self.send_response(status)
            for k, v in resp_headers.items():
                if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                    self.send_header(k, v)
            self.send_header("content-length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)

        def do_POST(self) -> None:  # noqa: N802
            self._do("POST")

        def do_GET(self) -> None:  # noqa: N802
            self._do("GET")

        def log_message(self, *args: Any) -> None:  # silence default logging
            pass

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
