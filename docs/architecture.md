# Architecture

ScoutCTX is a deliberately small pipeline. Each stage owns one auditable decision:

```text
task + settings
      │
      ▼
file discovery ── Git ls-files or bounded filesystem walk
      │
      ▼
text scan ─────── binary, size, ignore, and path-safety checks
      │
      ▼
ranking ───────── task terms + path + content + anchors + Git status
      │
      ▼
excerpting ────── relevant line windows fitted to a character budget
      │
      ▼
redaction ─────── assignments + private keys + known token shapes
      │
      ▼
rendering ─────── portable Markdown or versioned JSON
```

## Modules

- `config.py` loads and validates `.scoutctx.toml`.
- `git.py` contains timeout-bounded, failure-tolerant Git calls.
- `scanner.py` discovers safe paths and reads bounded text content.
- `ranking.py` turns a task into terms, scores candidates, and selects excerpts.
- `redact.py` removes common secrets before rendering.
- `brief.py` composes the pipeline and allocates the token budget.
- `render.py` owns deterministic Markdown and JSON serialization.
- `cli.py` validates user input and handles stdout or file output.

## Design decisions

### Why lexical ranking?

It is fast, explainable, deterministic, local, and requires no model download. ScoutCTX is a context preprocessor, not another agent. More sophisticated ranking can be added later as an opt-in profile without weakening the baseline.

### Why approximate tokens?

Tokenizers differ by model and introduce dependencies. ScoutCTX uses the common four-characters-per-token approximation and reserves space for document structure. The result is a portable target rather than a model-specific hard guarantee.

### Why skip symlinks?

A repository can contain a symlink to content outside its root. Following it could silently include unrelated or sensitive files. Skipping symlinks makes the trust boundary match the repository boundary.

### Why Markdown first?

Markdown is inspectable by a human, accepted by every major coding agent, easy to version, and useful without integration work. JSON covers programmatic consumers with an explicit schema version.
