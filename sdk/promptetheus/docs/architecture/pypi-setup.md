# PyPI Trusted Publishing Setup

Use [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) (OpenID Connect via GitHub Actions). No long-lived API tokens in the repo.

## 1. PyPI account

1. Create an account at [pypi.org](https://pypi.org/account/register/) if needed.
2. Enable 2FA (required for publishing).

## 2. Add pending publisher (before first upload)

Go to: **Account settings → Publishing → Add a new pending publisher**

| Field | Value |
| --- | --- |
| **PyPI Project Name** | `promptetheus` |
| **Owner** | `obro79` |
| **Repository name** | `promptetheus` |
| **Workflow name** | `publish.yml` |
| **Environment name** | `pypi` |

Save. The project is created on PyPI when the first trusted publish succeeds.

## 3. GitHub environment (recommended)

In `https://github.com/obro79/promptetheus` → **Settings → Environments**:

1. Create environment named `pypi`.
2. Optionally restrict who can approve deployments (keeps publish access off casual collaborators).

The workflow in [`.github/workflows/publish.yml`](../../.github/workflows/publish.yml) already references `environment: pypi`.

## 4. First publish (claim the name)

After the repo is on GitHub with the workflow on `main`:

1. **Actions → Publish to PyPI → Run workflow** (workflow_dispatch), or
2. Create a GitHub Release (tag e.g. `v0.0.1`) to trigger the `release` event.

On success, `pip install promptetheus` works and the name is yours.

## 5. Bump versions

Edit `version` in [`packages/promptetheus/pyproject.toml`](../../packages/promptetheus/pyproject.toml) and `__version__` in `promptetheus/__init__.py`, commit, tag, release (or run workflow_dispatch again after bumping).

## Manual fallback (if trusted publish fails)

```bash
cd packages/promptetheus
python -m pip install build
python -m build
# one-time: twine upload dist/* with a PyPI API token
```

Prefer trusted publishing for ongoing releases.
