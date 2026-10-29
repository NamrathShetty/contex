# Contributing to ctxvc

Thanks for your interest in contributing! This document explains how to set up a
development environment and the conventions the project follows.

## Development setup

```bash
# Clone and create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

# Install the package with all dev + optional dependencies
pip install -e ".[dev,all]"
```

The package uses a `src/` layout. The core install only requires `networkx`;
heavier capabilities are optional extras:

| Extra      | Enables                                  |
|------------|------------------------------------------|
| `tokens`   | Accurate token counts via `tiktoken`     |
| `semantic` | Neural embeddings via sentence-transformers |
| `s3`       | S3/MinIO/R2 remotes via `boto3`          |
| `qdrant`   | Remote vector index via `qdrant-client`  |
| `all`      | All of the above                         |
| `dev`      | Test + lint + build tooling              |

## Running the checks

```bash
ruff check .          # lint (and import sorting)
ruff format .         # auto-format (optional)
mypy                  # static type checking
pytest                # run the test suite
pytest --cov=ctxvc    # with coverage
```

All of these run in CI on every pull request against Python 3.11, 3.12 and 3.13.

## Conventions

- **Optional dependencies are lazy-imported** inside the function that needs
  them and raise a `CtxvcError` with an install hint if missing. Never add a
  hard import of an optional dependency at module top level.
- **The object/snapshot store is immutable and content-addressed.** Do not
  introduce mutable state into it; only refs are mutable (and use
  compare-and-swap).
- **The semantic / vector layer is a derived, rebuildable cache** — never a
  source of truth. Always pin the embedder label alongside stored vectors.
- Type hints use PEP 604 (`X | None`) with `from __future__ import annotations`.
- User-facing errors should raise `CtxvcError`.

## Pull requests

1. Fork the repo and create a feature branch.
2. Add or update tests for your change.
3. Make sure `ruff check .` and `pytest` pass locally.
4. Update `CHANGELOG.md` under the `Unreleased` section.
5. Open a PR with a clear description of the change and motivation.

## Reporting bugs / requesting features

Use the GitHub issue templates. Please include the ctxvc version
(`ctxvc --version` once released, or the commit SHA) and your Python version.
