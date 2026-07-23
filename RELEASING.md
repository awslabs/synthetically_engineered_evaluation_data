# Releasing seed-data to PyPI

This document is the complete, standalone guide to releasing a new version of
`seed-data`. It assumes no prior context and can be shared as-is.

- **Package:** [`seed-data` on PyPI](https://pypi.org/project/seed-data/)
- **Repository:** `awslabs/synthetically_engineered_evaluation_data`
- **Publish workflow:** `.github/workflows/publish.yml`

---

## TL;DR

Publishing a **GitHub Release** publishes the package. That is the whole process.

1. Make sure `main` has everything you want to ship.
2. Repo → **Releases** → **Draft a new release** → create tag `vX.Y.Z` on `main` → **Publish release**.
3. Repo → **Actions** → watch **Publish to PyPI** (approve if prompted).
4. Confirm the new version at <https://pypi.org/project/seed-data/>.

No files to edit, no tokens, no `twine`.

---

## How the automation works

- **Version comes from the git tag.** The project uses
  [setuptools-scm](https://setuptools-scm.readthedocs.io/). A release tagged `v0.1.0`
  builds version `0.1.0` (the leading `v` is stripped). Nothing in `pyproject.toml`
  needs to change between releases — the version field there is dynamic.
- **A published GitHub Release triggers the build.** The `publish.yml` workflow runs on
  the `release: published` event. It checks out the tagged commit (with full history so
  setuptools-scm can read the tag), builds the source distribution and wheel with
  `uv build`, and uploads them to PyPI.
- **Uploads use PyPI Trusted Publishing (OIDC).** GitHub authenticates to PyPI directly
  using a short-lived identity token. There is **no PyPI API token** stored in the repo
  or in GitHub secrets — nothing to leak, expire, or rotate.

---

## One-time setup (already done for this project)

New maintainers do **not** need to redo these. They are documented here so the trust
chain is understandable and reproducible if the project is ever forked or moved.

### 1. PyPI trusted publisher

On PyPI: project **seed-data** → **Manage** → **Publishing** → **Add a new publisher**
(GitHub tab), with:

| Field | Value |
| --- | --- |
| Owner | `awslabs` |
| Repository | `synthetically_engineered_evaluation_data` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

### 2. GitHub `pypi` environment

Repo → **Settings** → **Environments** → **New environment**, named exactly `pypi`.
Optionally add protection rules (required reviewers, restrict to `main`) — these then
gate every release.

> **The environment name `pypi` must match in all three places:** the workflow
> (`environment: pypi`), the PyPI publisher config, and the GitHub environment. A
> mismatch here is the single most common cause of a failed first release.

---

## Step-by-step release

### 1. Prepare `main`

The workflow builds from the tagged commit, so merge everything intended for this
version first. Recommended pre-flight:

```bash
git checkout main && git pull
make test          # run the unit test suite
```

### 2. Choose the version

Use [semantic versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`:

- **PATCH** (`0.0.3 → 0.0.4`): bug fixes, docs, no behavior change.
- **MINOR** (`0.0.4 → 0.1.0`): new features, backward compatible.
- **MAJOR** (`0.1.0 → 1.0.0`): breaking changes.

Check the [current version on PyPI](https://pypi.org/project/seed-data/) and pick the
next one.

> **A version number can never be reused on PyPI**, even if you delete the release or
> yank the version. Choose deliberately.

### 3. Draft and publish the release

1. Repo → **Releases** → **Draft a new release**.
2. **Choose a tag** → type the new tag, e.g. `v0.1.0` → **Create new tag on publish**.
3. **Target:** `main`.
4. Add a title and release notes (GitHub's "Generate release notes" button is a good start).
5. Click **Publish release**.

### 4. Watch the workflow

Repo → **Actions** → **Publish to PyPI** run for your tag. If the `pypi` environment
requires a reviewer, the run pauses for approval there. On success, the package is live.

### 5. Verify

```bash
# In a clean virtual environment:
pip install "seed-data==0.1.0"
python -c "import importlib.metadata as m; print(m.version('seed-data'))"
seed-data --help
```

Also confirm the version appears at <https://pypi.org/project/seed-data/>.

---

## Tag conventions

- Format: `vMAJOR.MINOR.PATCH` — e.g. `v0.0.4`, `v0.1.0`, `v1.0.0`.
- The tag **is** the published version. Double-check the tag string before publishing;
  a typo such as `v0.04` produces a wrong, unfixable version number on PyPI.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Upload step fails with "not a trusted publisher" / OIDC error | Workflow filename, repo owner/name, or environment name doesn't match the PyPI publisher config | Compare all three against the PyPI publisher settings; the environment must be exactly `pypi`. |
| Workflow never starts | A tag was pushed from the CLI without creating a GitHub **Release** | The trigger is `release: published`, not a bare tag. Always use the GitHub Releases UI. |
| Built version is `0.1.devN+g<sha>` instead of `X.Y.Z` | Built from an untagged commit, or tags weren't fetched | Ensure the release targets the tagged commit; the workflow uses `fetch-depth: 0` so CI has the tags. |
| Workflow paused, not failed | The `pypi` environment has a required reviewer | Approve the deployment in the Actions run. |
| Upload rejected as a duplicate | That version already exists on PyPI | Bump to a new, unused version and release again. |
| Nothing gets published on failure | Expected — the upload is the last step | Fix the cause and re-run; a failed run publishes nothing. |

---

## What you never have to do

- Edit a version number in `pyproject.toml` — setuptools-scm derives it from the tag.
- Run `twine`, `uv publish`, or any manual upload command.
- Create, store, or rotate a PyPI API token.
