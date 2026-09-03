"""A real multi-turn, tool-using ReAct agent — a *full* agent, not isolated calls.

It reasons over several turns and calls a local calculator tool until it can answer.
Point its LLM ``call`` at the costbomb proxy and every reasoning turn is metered as
one agent run — proving costbomb captures a whole agent's model cost end-to-end, not
a single request.

The LLM client is injected (``call_llm(messages) -> assistant_text``) so the agent is
testable offline and provider-agnostic.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable

SYSTEM = (
    "You are a precise reasoning agent. For ANY arithmetic, reply EXACTLY "
    "'CALC: <expression>' (e.g. 'CALC: 12*7') and wait for the tool result. "
    "When you have the final result, reply EXACTLY 'ANSWER: <value>'. Never compute "
    "arithmetic yourself."
)

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


def calculator(expr: str) -> str:
    """A safe arithmetic evaluator — the agent's one tool."""
    def _ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.operand))
        raise ValueError("unsupported expression")
    try:
        return str(_ev(ast.parse(expr.strip(), mode="eval").body))
    except Exception:  # noqa: BLE001 - a tool error is a normal agent signal
        return "error"


def run(
    question: str,
    call_llm: Callable[[list[dict[str, str]]], str],
    *,
    max_turns: int = 5,
) -> dict[str, int]:
    """Drive the agent to an answer. Returns turn/tool counts (model calls = turns)."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    turns = tool_calls = 0
    for _ in range(max_turns):
        reply = call_llm(messages)
        turns += 1
        messages.append({"role": "assistant", "content": reply})
        up = reply.upper()
        if "ANSWER:" in up:
            break
        if "CALC:" in up:
            expr = reply[up.index("CALC:") + 5:].strip().splitlines()[0]
            tool_calls += 1
            messages.append({"role": "user", "content": f"TOOL result: {calculator(expr)}"})
        else:
            messages.append({"role": "user", "content": "Reply with CALC: or ANSWER:."})
    return {"turns": turns, "tool_calls": tool_calls}
