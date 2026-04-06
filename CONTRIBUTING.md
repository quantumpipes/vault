# Contributing to qp-vault

Thank you for your interest in contributing to qp-vault. This document explains how to get involved.

## Repository Structure

```
vault/
├── src/qp_vault/       <- Source code
│   ├── core/           <- Business logic (chunker, search, lifecycle)
│   ├── storage/        <- Storage backends (SQLite, PostgreSQL)
│   ├── processing/     <- File parsers (text, transcripts)
│   ├── audit/          <- Audit providers (log, capsule)
│   ├── integrity/      <- Health detection (staleness, duplicates)
│   ├── plugins/        <- Plugin system (registry, decorators)
│   ├── integrations/   <- Framework adapters (FastAPI)
│   └── cli/            <- Command-line interface
├── tests/              <- Test suite (375+ tests)
├── docs/               <- Documentation
└── examples/           <- Usage examples
```

## Getting Started

```bash
git clone https://github.com/quantumpipes/vault.git
cd vault
pip install -e ".[sqlite,cli,fastapi,integrity,dev]"
make test
```

## Types of Contributions

### Bug Fixes

- Open an issue describing the bug
- Include a minimal reproduction case
- Submit a PR with a test that fails before the fix and passes after

### New Storage Backends

Implement the `StorageBackend` Protocol in `src/qp_vault/protocols.py`:

```python
class StorageBackend(Protocol):
    async def initialize(self) -> None: ...
    async def store_resource(self, resource: Resource) -> str: ...
    async def get_resource(self, resource_id: str) -> Resource | None: ...
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...
    # ... see protocols.py for full interface
```

### New Parsers

Use the `@parser` decorator:

```python
from qp_vault.plugins import parser

@parser("my-format")
class MyParser:
    supported_extensions = {".myf"}
    async def parse(self, path: Path) -> ParseResult:
        return ParseResult(text=extract(path))
```

### New Embedding Providers

Use the `@embedder` decorator:

```python
from qp_vault.plugins import embedder

@embedder("my-model")
class MyEmbedder:
    dimensions = 768
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return my_model.encode(texts)
```

### Documentation

Improvements to README, API docs, examples, and tutorials.

## Code Standards

- **Type hints** on all function signatures
- **Docstrings** on all public classes and methods
- **Tests** for all new functionality (target 100% coverage)
- **No hardcoded values**: use VaultConfig for all configurable settings
- **Async-first**: all I/O operations must be async
- **No deprecated crypto**: SHA3-256 only, no MD5/SHA1/RSA

## Running Tests

```bash
make test          # Run full test suite with coverage
make lint          # Run ruff linter
make typecheck     # Run mypy type checker
make test-all      # All of the above
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch from `main`
3. Write tests alongside your code
4. Ensure `make test-all` passes
5. Submit a pull request

## Security

If you discover a security vulnerability, please report it privately. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
