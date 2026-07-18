"""Vendored, authoritative Swarm Proof contracts.

costbomb does **not** own these shapes — they are the shared, versioned contracts
that live in the ``stampede`` repository (ARCHITECTURE §6.2, ADR-8). We vendor a
faithful copy here so ``costbomb-core`` builds and tests without a hard import on
stampede, and so extraction from stampede stays a *packaging* move, not a rewrite.

Rule: consume these verbatim; extend only inside the ``swarmproof.*`` namespace.
When stampede reaches v0.2 and publishes them as a package, this directory is
replaced by that dependency. Keep the attribute *names* identical.
"""
