# Publishing costbomb to PyPI

costbomb publishes via **PyPI Trusted Publishing** (OIDC) — GitHub Actions proves the
repo's identity to PyPI directly, so there is **no API token or secret to manage**.
The workflow (`.github/workflows/publish.yml`) is already wired; it needs a one-time
setup on PyPI and GitHub, then it runs on every published Release.

## One-time setup (≈2 minutes)

### 1. Register the trusted publisher on PyPI
Do this *before* the first upload — use a **pending** publisher so you don't need the
project to exist yet.

1. Log in to <https://pypi.org> → your account → **Publishing** (`/manage/account/publishing/`).
2. Under **Add a new pending publisher**, fill in exactly:
   | Field | Value |
   |-------|-------|
   | PyPI Project Name | `costbomb` |
   | Owner | `swarmproof` |
   | Repository name | `costbomb` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |
3. **Add**.

### 2. Create the `pypi` environment on GitHub
The workflow's `publish-pypi` job declares `environment: pypi`.

1. GitHub → `swarmproof/costbomb` → **Settings → Environments → New environment** → name it `pypi`.
2. (Optional) add yourself as a required reviewer so every publish needs one click of approval.

## Publish

- **The already-released v0.2.0**: re-run the failed publish workflow now that setup is
  done — Actions → `publish` → the v0.2.0 run → **Re-run failed jobs**. The `build` job
  already passed; only `publish-pypi` needs to re-run.
- **Future versions**: bump the version, tag `vX.Y.Z`, and publish a GitHub Release —
  the workflow fires automatically.

## Verify

```bash
pip install costbomb            # from PyPI, once published
costbomb --help
```

## After PyPI is live

Switch the sibling pins from the git URL to the published package:

- `stampede`'s `economic` extra: `costbomb @ git+…@v0.2.0` → `costbomb>=0.2`
  (and drop `tool.hatch.metadata.allow-direct-references`, no longer needed).

Until then, the git-URL pin keeps everything installable straight from the tag.
