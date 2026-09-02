"""costbomb CLI — the standalone entrypoint (ENTRYPOINT B, ARCHITECTURE §6).

A thin wrapper: parse args → build a Target → run the FuzzEngine → render the report
→ apply the CI gate → set the exit code. All the IP lives in ``costbomb-core``; this
file adds no logic the embedded path needs.

    costbomb run --target ./agent.py:handler --budget 0.50 --fail-on-regression
    costbomb run                       # zero-config demo against the built-in FakeTarget
    costbomb baseline update --target ./agent.py:handler
    costbomb attacks
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from costbomb.attacks import registry
from costbomb.attacks.base import TargetCapabilities
from costbomb.ci import BASELINE_FILE, Baseline, gate
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.export import write_findings_json, write_otel_json
from costbomb.pricing import PriceTable
from costbomb.report import render_terminal
from costbomb.targets.base import Target

app = typer.Typer(add_completion=False, help="Denial-of-wallet fuzzing for agent systems.")
console = Console()


def _build_target(spec: str) -> Target:
    """Resolve a --target spec into a Target adapter (the target factory)."""
    if spec == "fake":
        from costbomb.targets.fake import FakeTarget

        return FakeTarget()
    if spec.startswith("mock:"):
        # `mock:<handler-spec>` — the safe default; effects hit mockworld fakes (NFR-5).
        from costbomb.targets.mockworld_target import MockworldTarget

        return MockworldTarget(spec[len("mock:"):])
    if spec.startswith(("http://", "https://")):
        from costbomb.targets.http_target import HTTPTarget

        return HTTPTarget(spec)
    if ":" in spec or spec.endswith(".py"):
        from costbomb.targets.python_target import PythonTarget

        # Conservative default caps: tools yes, spawn no (recursion is skipped and
        # reported unless the target is known to spawn). Honest coverage (REQ-AL-5).
        caps = TargetCapabilities(has_tools=True, can_spawn=False, accepts_documents=True)
        return PythonTarget(spec, capabilities=caps)
    raise typer.BadParameter(f"unrecognized target spec: {spec!r}")


def _load_prices(price_table: str | None) -> PriceTable:
    return PriceTable.from_path(price_table) if price_table else PriceTable.default()


def _make_config(
    *, seed: int, max_spend: float, budget: float | None, k: int, classes: str | None,
    dry_run: bool, allow_side_effects: bool, generations: int, use_llm: bool = False,
    fitness: str = "total_usd",
) -> SearchConfig:
    class_tuple = tuple(c.strip() for c in classes.split(",")) if classes else None
    return SearchConfig(
        seed=seed,
        max_spend_usd=max_spend,
        budget_usd=budget,
        k=k,
        max_generations=generations,
        classes=class_tuple,
        dry_run=dry_run,
        allow_side_effects=allow_side_effects,
        use_llm=use_llm,
        fitness=fitness,
    )


@app.command()
def run(
    target: str = typer.Option("fake", "--target", "-t", help="fake | module:func | ./file.py:func | http://..."),
    budget: float | None = typer.Option(None, "--budget", help="CI budget ceiling in USD (worst-case must stay under)."),
    max_spend: float = typer.Option(2.0, "--max-spend", help="Hard cap on the fuzzer's OWN spend (NFR-1)."),
    seed: int = typer.Option(1337, "--seed", help="Deterministic search seed."),
    k: int = typer.Option(5, "--k", help="Runs per candidate; fitness is p95 over k."),
    fitness: str = typer.Option("total_usd", "--fitness", help="Maximize 'total_usd' (direct bill) or 'blast_radius_usd' (incl. downstream side-effects)."),
    classes: str | None = typer.Option(None, "--classes", help="Comma list to restrict attack classes."),
    generations: int = typer.Option(200, "--generations", help="Max search generations."),
    fail_on_regression: bool = typer.Option(False, "--fail-on-regression", help="Gate against .costbomb-baseline.json."),
    use_llm: bool = typer.Option(False, "--use-llm", help="LLM-assisted mutation (default off; cheap/local, NFR-4)."),
    llm_model: str = typer.Option("ollama:llama3", "--llm-model", help="Price-table key for the mutator model."),
    llm_base_url: str = typer.Option("http://localhost:11434/v1", "--llm-base-url", help="OpenAI-compatible endpoint for the mutator."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estimate only — zero paid calls, fast CI smoke (NFR-7)."),
    allow_side_effects: bool = typer.Option(False, "--allow-side-effects", help="Authorize hitting a real side-effecting target (NFR-5)."),
    price_table: str | None = typer.Option(None, "--price-table", help="Override the vendored price table (JSON)."),
    baseline_path: str = typer.Option(BASELINE_FILE, "--baseline", help="Baseline file for the regression gate."),
    findings_out: str | None = typer.Option(None, "--findings-out", help="Write findings.json here (REQ-RP-5)."),
    otel_out: str | None = typer.Option(None, "--otel-out", help="Write OTel GenAI-profile traces here (REQ-RP-5)."),
) -> None:
    """Fuzz a target for denial-of-wallet inputs and (optionally) gate CI."""
    prices = _load_prices(price_table)
    tgt = _build_target(target)
    cfg = _make_config(
        seed=seed, max_spend=max_spend, budget=budget, k=k, classes=classes,
        dry_run=dry_run, allow_side_effects=allow_side_effects, generations=generations,
        use_llm=use_llm, fitness=fitness,
    )
    mutator = None
    if use_llm:
        from costbomb.mutator import LLMMutator

        mutator = LLMMutator(model=llm_model, base_url=llm_base_url, prices=prices)
        console.print(f"[dim]LLM mutator: {llm_model} @ {llm_base_url} (fallback: template)[/dim]")
    rf = FuzzEngine(tgt, prices=prices, config=cfg, mutator=mutator).run()
    render_terminal(rf, console=console)

    if findings_out:
        write_findings_json(rf, findings_out)
        console.print(f"[dim]findings → {findings_out}[/dim]")
    if otel_out:
        write_otel_json(rf, otel_out)
        console.print(f"[dim]otel traces → {otel_out}[/dim]")

    # --- CI gate ---
    if budget is not None or fail_on_regression:
        base = None
        if fail_on_regression and Path(baseline_path).exists():
            base = Baseline.load(baseline_path)
        elif fail_on_regression:
            console.print(f"[yellow]no baseline at {baseline_path}; run `costbomb baseline update` first.[/yellow]")
        result = gate(rf, prices=prices, baseline=base, budget_usd=budget, fail_on_regression=fail_on_regression)
        if result.passed:
            console.print("[bold green]✓ gate passed[/bold green]")
        else:
            console.print(f"[bold red]✗ gate failed:[/bold red] {'; '.join(result.reasons)}")
            for r in result.regressions:
                sep = "price-drift-separated" if r.price_drift_separated else "raw compare"
                console.print(
                    f"  [red]regression[/red] {r.attack_class}: "
                    f"${r.now_usd:.4f} > ${r.baseline_repriced_usd:.4f}×(1+{r.tolerance:.0%}) [{sep}]"
                )
            for o in result.over_budget:
                console.print(f"  [red]over budget[/red] {o.attack_class}: ${o.worst_usd:.4f} > ${o.budget_usd:.2f}")
        raise typer.Exit(code=result.exit_code)


@app.command()
def estimate(
    target: str = typer.Option("fake", "--target", "-t"),
    seed: int = typer.Option(1337, "--seed"),
    classes: str | None = typer.Option(None, "--classes"),
    generations: int = typer.Option(200, "--generations"),
    price_table: str | None = typer.Option(None, "--price-table"),
) -> None:
    """Dry-run estimate — no paid calls (alias for `run --dry-run`)."""
    prices = _load_prices(price_table)
    tgt = _build_target(target)
    cfg = _make_config(
        seed=seed, max_spend=2.0, budget=None, k=1, classes=classes,
        dry_run=True, allow_side_effects=False, generations=generations,
    )
    rf = FuzzEngine(tgt, prices=prices, config=cfg).run()
    render_terminal(rf, console=console)


baseline_app = typer.Typer(help="Manage the CI regression baseline.")
app.add_typer(baseline_app, name="baseline")


@baseline_app.command("update")
def baseline_update(
    target: str = typer.Option("fake", "--target", "-t"),
    seed: int = typer.Option(1337, "--seed"),
    max_spend: float = typer.Option(2.0, "--max-spend"),
    k: int = typer.Option(5, "--k"),
    generations: int = typer.Option(200, "--generations"),
    tolerance: float = typer.Option(0.10, "--tolerance", help="Allowed drift before a regression fails."),
    price_table: str | None = typer.Option(None, "--price-table"),
    baseline_path: str = typer.Option(BASELINE_FILE, "--baseline"),
    allow_side_effects: bool = typer.Option(False, "--allow-side-effects"),
) -> None:
    """Regenerate the committed baseline INTENTIONALLY (never auto-updated, REQ-CI-6)."""
    prices = _load_prices(price_table)
    tgt = _build_target(target)
    cfg = _make_config(
        seed=seed, max_spend=max_spend, budget=None, k=k, classes=None,
        dry_run=False, allow_side_effects=allow_side_effects, generations=generations,
    )
    rf = FuzzEngine(tgt, prices=prices, config=cfg).run()
    Baseline.from_findings(rf, tolerance=tolerance).save(baseline_path)
    render_terminal(rf, console=console)
    console.print(f"[bold green]baseline written → {baseline_path}[/bold green] "
                  f"(price table {prices.version}, tolerance {tolerance:.0%})")


@app.command()
def attacks() -> None:
    """List the registered attack classes."""
    for a in registry.all():
        console.print(f"[bold]{a.name}[/bold] — {a.description}")


@app.command()
def proxy(
    upstream: str = typer.Option(..., "--upstream", help="Real provider base URL to forward to (e.g. https://api.openai.com)."),
    port: int = typer.Option(8100, "--port", help="Local port to listen on."),
    price_table: str | None = typer.Option(None, "--price-table"),
) -> None:
    """Run the metering proxy — point your agent's model base_url here (REQ-CM-5c)."""
    prices = _load_prices(price_table)
    from costbomb.proxy_server import run_server

    console.print(
        f"[bold]costbomb proxy[/bold] → {upstream}\n"
        f"listening on [bold]http://127.0.0.1:{port}[/bold] — set your agent's model "
        f"base_url to this, send [dim]x-costbomb-run[/dim] headers to attribute runs.\n"
        f"[dim]price table {prices.version} · Ctrl-C to stop[/dim]"
    )
    run_server(upstream=upstream, port=port, prices=prices)


@app.command("price")
def price(
    price_table: str | None = typer.Option(None, "--price-table"),
) -> None:
    """Show the loaded price table."""
    pt = _load_prices(price_table)
    console.print(f"price table [bold]{pt.version}[/bold] (source: {pt.source})")
    console.print(f"models: {', '.join(sorted(pt.models))}")
    console.print(f"tools: {', '.join(sorted(pt.tools))}")


if __name__ == "__main__":  # pragma: no cover
    app()
