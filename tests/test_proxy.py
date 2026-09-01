"""Proxy meter — zero-instrumentation metering of real agents (REQ-CM-5c)."""

from __future__ import annotations

import json

import pytest

from costbomb.attacks.base import Input
from costbomb.pricing import PriceTable
from costbomb.proxy import (
    ProxyMeter,
    detect_and_parse,
    parse_anthropic_usage,
    parse_openai_usage,
)
from costbomb.proxy_server import RunStore, proxy_handle
from costbomb.targets.base import TargetContext
from costbomb.targets.proxy_target import ProxyTarget

OPENAI_RESP = {
    "model": "gpt-4o",
    "choices": [{"message": {"content": "hi"}}],
    "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "prompt_tokens_details": {"cached_tokens": 200},
        "completion_tokens_details": {"reasoning_tokens": 100},
    },
}

ANTHROPIC_RESP = {
    "model": "claude-opus-4-8",
    "usage": {
        "input_tokens": 2000,
        "output_tokens": 200,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 500,
    },
}
# hand: 2000*3e-6 + 200*1.5e-5 + 1000*3e-7 + 500*3.75e-6 = 0.011175
ANTHROPIC_EXPECTED_USD = 0.011175


def test_parse_openai_splits_cached_and_reasoning() -> None:
    call = parse_openai_usage(OPENAI_RESP)
    assert call.model == "openai:gpt-4o"
    assert call.input_tokens == 800  # prompt 1000 − 200 cached
    assert call.cache_read_tokens == 200
    assert call.output_tokens == 500
    assert call.reasoning_tokens == 100


def test_parse_anthropic_maps_cache_fields() -> None:
    call = parse_anthropic_usage(ANTHROPIC_RESP)
    assert call.model == "anthropic:claude-opus-4-8"
    assert call.input_tokens == 2000
    assert call.cache_read_tokens == 1000
    assert call.cache_write_tokens == 500


def test_detect_and_parse_routes_by_shape() -> None:
    assert detect_and_parse(OPENAI_RESP).provider == "openai"
    assert detect_and_parse(ANTHROPIC_RESP).provider == "anthropic"
    with pytest.raises(ValueError):
        detect_and_parse({"nonsense": True})


def test_proxy_meter_brackets_and_prices_a_run(prices: PriceTable) -> None:
    pm = ProxyMeter(prices)
    pm.start_run(attack_class="retry-loop")
    pm.record(ANTHROPIC_RESP)
    pm.record(ANTHROPIC_RESP)
    trace = pm.finish_run()
    bd = pm.cost(trace)
    assert pm.calls_recorded == 2
    assert bd.total_usd == pytest.approx(2 * ANTHROPIC_EXPECTED_USD)


def test_proxy_target_meters_without_instrumentation(prices: PriceTable) -> None:
    pm = ProxyMeter(prices)

    # A "driver" that triggers an agent whose model calls flow through the proxy.
    def driver(text: str, ctx: TargetContext) -> None:
        pm.record(ANTHROPIC_RESP)
        pm.record(OPENAI_RESP)

    target = ProxyTarget(driver, pm)
    trace = target.invoke(Input(text="x", attack_class="retry-loop"), TargetContext(seed=1))
    bd = pm.cost(trace)
    assert bd.total_usd > ANTHROPIC_EXPECTED_USD  # both calls metered
    assert bd.n_model_calls == 2


def test_proxy_server_forwards_meters_and_returns_trace(prices: PriceTable) -> None:
    store = RunStore(prices)

    def stub_forward(method, url, headers, body):
        # pretend upstream returned an Anthropic response
        return 200, {"content-type": "application/json"}, json.dumps(ANTHROPIC_RESP).encode()

    # 1. start a run
    s, _, _ = proxy_handle("POST", "/costbomb/run/start", {},
                           b'{"run_id":"r1","attack_class":"retry-loop"}',
                           upstream="http://up", store=store, forward=stub_forward)
    assert s == 200 and store.active == 1

    # 2. the agent makes a model call carrying the run header → forwarded + metered
    s, _, body = proxy_handle("POST", "/v1/messages", {"x-costbomb-run": "r1"}, b"{}",
                              upstream="http://up", store=store, forward=stub_forward)
    assert s == 200
    assert json.loads(body) == ANTHROPIC_RESP  # response returned to the agent untouched

    # 3. finish → metered trace + total
    s, _, body = proxy_handle("POST", "/costbomb/run/finish", {}, b'{"run_id":"r1"}',
                              upstream="http://up", store=store, forward=stub_forward)
    assert s == 200
    result = json.loads(body)
    assert result["total_usd"] == pytest.approx(ANTHROPIC_EXPECTED_USD)
    assert store.active == 0


def test_proxy_server_ignores_non_json_upstream(prices: PriceTable) -> None:
    store = RunStore(prices)
    store.start("r1")

    def stub_forward(method, url, headers, body):
        return 200, {"content-type": "text/event-stream"}, b"data: streaming chunk\n\n"

    s, _, body = proxy_handle("POST", "/v1/messages", {"x-costbomb-run": "r1"}, b"{}",
                              upstream="http://up", store=store, forward=stub_forward)
    assert s == 200
    assert body == b"data: streaming chunk\n\n"  # forwarded untouched, not metered, no crash


def test_proxy_server_unknown_run_finish_404(prices: PriceTable) -> None:
    store = RunStore(prices)
    s, _, _ = proxy_handle("POST", "/costbomb/run/finish", {}, b'{"run_id":"nope"}',
                           upstream="http://up", store=store, forward=lambda *a: (200, {}, b"{}"))
    assert s == 404
