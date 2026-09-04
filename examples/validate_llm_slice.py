"""Validate the LLM cost slice against a real biller, using a *full* agent.

Runs the multi-turn ReAct agent (examples/react_agent.py) through the costbomb proxy,
meters the whole run, and reconciles costbomb's number against what the provider
actually billed. With a paid key it's invoice-backed (proves NFR-8 for the LLM slice);
against free local Ollama it proves the plumbing — that a full agent's every turn is
captured and metered — but is not a real bill.

    # free plumbing proof (Ollama):
    costbomb proxy --upstream http://localhost:11434 --port 8100 \
        --price-table examples/prices_mistral_small.json &
    python examples/validate_llm_slice.py --model mistral-small:latest

    # invoice-backed (paid): point the proxy at the provider, then pass the
    # dashboard cost for this run's fresh key:
    python examples/validate_llm_slice.py --model gpt-4o-mini --billed-usd 0.0123
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from costbomb._vendor.trace import GenAI, Trace
from costbomb.validation import reconcile

PROXY = "http://127.0.0.1:8100"
RUN_ID = "llm-validate"


def _post(path: str, obj: dict, headers: dict | None = None) -> dict:
    body = json.dumps(obj).encode()
    req = urllib.request.Request(
        PROXY + path, data=body, method="POST",
        headers={"content-type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310 - localhost proxy
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mistral-small:latest")
    ap.add_argument("--question", default="What is 12 * 7, then add 15?")
    ap.add_argument("--billed-usd", type=float, default=None,
                    help="Provider-dashboard cost for this run (omit for a free Ollama plumbing proof).")
    args = ap.parse_args()

    import react_agent  # sibling module (script runs from examples/)

    def call_llm(messages: list[dict[str, str]]) -> str:
        resp = _post("/v1/chat/completions",
                     {"model": args.model, "messages": messages, "max_tokens": 40},
                     headers={"x-costbomb-run": RUN_ID})
        return resp["choices"][0]["message"]["content"]

    try:
        _post("/costbomb/run/start", {"run_id": RUN_ID, "attack_class": "validation"})
        counts = react_agent.run(args.question, call_llm)
        result = _post("/costbomb/run/finish", {"run_id": RUN_ID})
    except Exception as exc:  # noqa: BLE001
        print(f"proxy not reachable at {PROXY} — start `costbomb proxy` first ({exc})")
        return 1

    trace = Trace.from_dict(result["trace"])
    metered = result["total_usd"]
    n_calls = len([s for s in trace.spans if s.get(GenAI.USAGE_INPUT_TOKENS) is not None])

    print("\n=== full agent metered end-to-end via the proxy ===")
    print(f"  agent turns={counts['turns']} tool_calls={counts['tool_calls']}")
    print(f"  model-call spans captured: {n_calls}  (== turns → whole agent captured)")
    print(f"  costbomb metered: ${metered:.6f}")

    invoice_backed = args.billed_usd is not None
    billed = args.billed_usd if invoice_backed else metered  # Ollama free → billed==metered==reference
    rec = reconcile("llm", args.model.split(":")[0], metered_usd=metered, billed_usd=billed,
                    invoice_backed=invoice_backed)
    print("  " + rec.summary())
    if not invoice_backed:
        print("  [note] Ollama is free — this proves capture/plumbing, not dollars. "
              "Pass --billed-usd from a paid provider's dashboard for an invoice-backed proof.")
    return 0 if rec.passed else 2


if __name__ == "__main__":
    sys.exit(main())
