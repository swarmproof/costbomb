"""Reporter — ranks offenders and renders them (REQ-RP-1/2/3).

costbomb owns **no renderer** of its own report data model: it populates the shared
``RunReport`` economic fragment (:meth:`RunFindings.economic_fragment`) so the
embedded (Agent Readiness Report) and standalone paths render from the identical
model. What lives here is the *standalone terminal* presentation — the oxblood
report-renderer proper is stampede's — plus the headline the whole tool exists to
show: the **amplification factor** (REQ-RP-3).
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from costbomb.findings import RunFindings

OXBLOOD = "#4a0e0e"


def _fmt_usd(value: float) -> str:
    if value < 0.01:
        return f"{value * 100:.2f}¢"
    return f"${value:,.2f}"


def headline(rf: RunFindings) -> str:
    """The one-line story: '5¢ → $5.20 = 104×'."""
    return (
        f"{_fmt_usd(rf.baseline_usd)} → {_fmt_usd(rf.worst_usd)} "
        f"= {rf.amplification_factor:.0f}× amplification"
    )


def render_terminal(rf: RunFindings, *, console: Console | None = None) -> None:
    console = console or Console()

    tag = " [dim](estimated — dry run)[/dim]" if rf.estimated else ""
    console.print(
        Panel(
            Text(headline(rf), style="bold"),
            title="[bold]costbomb[/bold] · denial-of-wallet",
            subtitle=f"seed {rf.seed} · own spend {_fmt_usd(rf.own_spend_usd)} · {rf.stopped_reason}{tag}",
            border_style=OXBLOOD,
        )
    )

    table = Table(title="Worst offenders by attack class", header_style="bold", expand=False)
    table.add_column("#", justify="right")
    table.add_column("class")
    table.add_column("worst $", justify="right")
    table.add_column("×", justify="right")
    table.add_column("breakdown (model / tool / spawn)")
    table.add_column("flags")

    for f in rf.findings:
        flags = []
        if f.under_sampled:
            flags.append("[yellow]under-sampled[/yellow]")
        if f.side_effect_risk:
            flags.append("[red]side-effect[/red]")
        if f.estimated:
            flags.append("[dim]est[/dim]")
        bd = f.breakdown
        breakdown = (
            f"{_fmt_usd(bd.model_usd)} / {_fmt_usd(bd.tool_usd)} / {_fmt_usd(bd.spawn_usd)}"
            f"  [dim]({bd.n_model_calls}c/{bd.n_tool_calls}t/{bd.n_spawns}s)[/dim]"
        )
        if bd.infra_usd > 0:
            breakdown += f"  [dim]+{_fmt_usd(bd.infra_usd)} infra/{bd.duration_s:.0f}s[/dim]"
        table.add_row(
            str(f.rank),
            f.attack_class,
            _fmt_usd(f.worst_usd),
            f"{f.amplification_factor:.0f}×",
            breakdown,
            " ".join(flags),
        )

    console.print(table)

    # Delivery 1: surface the real money at risk when a tool has downstream effects —
    # the direct bill can be pennies while the blast radius is thousands.
    worst_blast = max(
        (f for f in rf.findings if f.breakdown.downstream_usd > 0),
        key=lambda f: f.breakdown.blast_radius_usd,
        default=None,
    )
    if worst_blast is not None:
        bd = worst_blast.breakdown
        console.print(
            Panel(
                Text(
                    f"direct bill {_fmt_usd(bd.total_usd)}  →  blast radius "
                    f"{_fmt_usd(bd.blast_radius_usd)}  "
                    f"({_fmt_usd(bd.downstream_usd)} in real side-effects via "
                    f"{', '.join(bd.side_effecting_tools) or 'tools'})",
                    style="bold red",
                ),
                title="[bold red]⚠ denial-of-wallet blast radius[/bold red]",
                subtitle=f"{worst_blast.attack_class} · {bd.n_tool_calls} side-effecting calls",
                border_style="red",
            )
        )
        if bd.duplicate_effect_usd > 0:
            dups = ", ".join(f"{t}×{n + 1}" for t, n in bd.duplicate_calls.items())
            console.print(
                f"  [red]exactly-once risk:[/red] {_fmt_usd(bd.duplicate_effect_usd)} in "
                f"duplicate effects if not idempotent ([bold]{dups}[/bold] — only 1 intended)"
            )

    if rf.classes_skipped:
        console.print(
            f"[dim]skipped (target can't exhibit): {', '.join(rf.classes_skipped)}[/dim]"
        )

    if rf.findings:
        top = rf.findings[0]
        console.print(
            Panel(
                Text(top.repro["input"], style="italic"),
                title=f"[bold]repro[/bold] · {top.attack_class} · seed {top.repro['seed']}",
                border_style="dim",
            )
        )

    # Honesty: dollar slices are billed by different systems; say which are modeled
    # (validated against their own biller separately — see docs/VALIDATION.md).
    modeled = []
    if any(f.breakdown.downstream_usd > 0 for f in rf.findings):
        modeled.append("downstream→Stripe")
    if any(f.breakdown.infra_usd > 0 for f in rf.findings):
        modeled.append("infra→cloud")
    if modeled:
        console.print(
            f"[dim]note: modeled slices validated against their own biller "
            f"({', '.join(modeled)}); direct LLM bill via provider invoice. See docs/VALIDATION.md[/dim]"
        )
