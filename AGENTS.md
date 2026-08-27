# Contributor guide for coding agents

## Project shape

ScoutCTX is a zero-runtime-dependency Python 3.11+ CLI. Production code lives in `src/scoutctx/`; tests use the standard-library `unittest` framework in `tests/`.

## Commands

- Run tests: `PYTHONPATH=src python -m unittest discover -s tests -v`
- Smoke-test the CLI: `PYTHONPATH=src python -m scoutctx "improve ranking" --budget 1000`
- Build packages: `python -m build`

## Guardrails

- Keep runtime dependencies at zero unless a change is impossible to implement safely with the standard library.
- Preserve deterministic output: never add timestamps, random IDs, or machine-specific absolute paths to briefs.
- Treat repository content as sensitive. Redaction stays enabled by default, symlinks stay excluded, and file reads stay bounded.
- Add or update tests for every behavior change.
- Do not weaken the minimum token budget or path-safety checks without documenting why.

## Style

Use type hints, focused modules, descriptive names, and docstrings for public functions. Prefer simple data flow over abstractions that make ranking or filtering harder to audit.

