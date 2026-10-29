# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Open-source project scaffolding: MIT `LICENSE`, `.gitignore`, `CONTRIBUTING.md`,
  `SECURITY.md`, issue/PR templates, Dependabot config, and a GitHub Actions CI
  workflow (lint + test matrix on Python 3.11–3.13).
- Declared runtime dependencies and optional-dependency extras
  (`tokens`, `semantic`, `s3`, `qdrant`, `all`, `dev`) in `pyproject.toml`.
- `py.typed` marker so downstream type checkers see ctxvc's type hints.
- Initial `pytest` test suite covering the object store, refs/branches/tags,
  semantic search, and the filesystem / S3 / Qdrant backends.
- S3-compatible remote backend (`S3Remote`) with ETag-based compare-and-swap.
- Qdrant-backed remote vector index (`vindex` commands) for shared semantic search.

## [0.1.0]

### Added
- Content-addressed snapshot store with gzip object compression.
- SQLite-backed refs, branches, tags, snapshot index, and agent handoffs.
- Multi-agent registration and centralized `snapshot-all`.
- Token budgeting, diff, and checkout/export.
- NetworkX knowledge-graph modeling, delta storage, and graph diff.
- Semantic layer: embeddings, semantic diff, and search.
- LangGraph trace ingestion.
- Pluggable remotes with filesystem push/pull.

[Unreleased]: https://github.com/namrathshetty/ctxvc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/namrathshetty/ctxvc/releases/tag/v0.1.0
