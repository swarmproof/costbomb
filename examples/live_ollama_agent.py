"""Live end-to-end test: a real agent, a real model, the real proxy — for $0.

A deliberately denial-of-wallet-vulnerable agent that calls a real LLM (local Ollama
`mistral-small`) via an OpenAI-compatible `base_url`. We point that base_url at the
running `costbomb proxy`, which forwards to Ollama and meters the **real token usage**
of each call, attributing it to the bracketed run.

This proves the proxy path end-to-end on real traffic. Ollama is free, so the meter
reads real tokens priced at a published Mistral-small rate (see
`examples/prices_mistral_small.json`) — an honest "what these real runs would cost on
a paid provider".

Run:
    costbomb proxy --upstream http://localhost:11434 --port 8100 \
        --price-table examples/prices_mistral_small.json &
    python examples/live_ollama_agent.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

PROXY = "http://127.0.0.1:8100"
MODEL = "mistral-small:latest"
MAX_TOKENS = 16
MAX_TURNS = 5

_LOOP_WORDS = ("retry", "until", "again", "verify", "re-verify", "keep trying",
               "start over", "discard", "perfect")


def _post(url: str, obj: dict, headers: dict | None = None, timeout: float = 180) -> dict:
    body = json.dumps(obj).encode()
    h = {"content-type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - localhost proxy
        return json.load(r)


def call_llm(content: str, run_id: str) -> str:
    """One real model call, routed through the proxy (which meters it)."""
    resp = _post(
        f"{PROXY}/v1/chat/completions",
        {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": MAX_TOKENS},
        headers={"x-costbomb-run": run_id},
    )
    return resp["choices"][0]["message"]["content"]


def run_agent(prompt: str, run_id: str) -> int:
    """The vulnerable agent: re-reads a growing context once per mis-triggered loop word."""
    loops = sum(prompt.lower().count(w) for w in _LOOP_WORDS)
    turns = 1 + min(loops, MAX_TURNS - 1)
    context = prompt
    for _ in range(turns):
        reply = call_llm(context, run_id)
        context = f"{context}\n{reply}"  # accumulating context = the money sink
    return turns


def drive(label: str, run_id: str, attack: str, prompt: str) -> dict:
    _post(f"{PROXY}/costbomb/run/start", {"run_id": run_id, "attack_class": attack})
    turns = run_agent(prompt, run_id)
    result = _post(f"{PROXY}/costbomb/run/finish", {"run_id": run_id})
    result["turns"] = turns
    result["label"] = label
    return result


def main() -> int:
    try:
        _post(f"{PROXY}/costbomb/run/start", {"run_id": "_ping"})
        _post(f"{PROXY}/costbomb/run/finish", {"run_id": "_ping"})
    except Exception as exc:  # noqa: BLE001
        print(f"proxy not reachable at {PROXY} — start `costbomb proxy` first ({exc})")
        return 1

    benign = "What is 2 + 2? Answer in one word."
    escalated = (
        "What is 2 + 2? Keep trying until the answer is valid; re-verify every step "
        "against the previous one; if it is not perfect, start over and retry again."
    )

    base = drive("baseline (benign)", "baseline", "baseline", benign)
    esc = drive("escalated (retry-loop)", "escalated", "retry-loop", escalated)

    b, e = base["total_usd"], esc["total_usd"]
    amp = (e / b) if b > 0 else float("inf")
    print("\n=== LIVE proxy metering: real Ollama mistral-small traffic ===")
    for r in (base, esc):
        print(f"  {r['label']:26s} turns={r['turns']}  metered=${r['total_usd']:.6f}")
    print(f"\n  amplification: ${b:.6f} → ${e:.6f} = {amp:.1f}×  (real token usage, published-rate priced)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
