# Architecture

ScoutCTX separates model-free context selection from sessions, transports, and
external agent harnesses:

```text
task + repository + Git + provider documents + session notes
                              |
       discover -> scan -> rank -> excerpt -> redact -> budget
                              |
                 ContextResult (Markdown/JSON)
                    /            |           \
                 Python         HTTP          MCP
                    \            |           /
                       external harness/model
                              |
                       session worktree
```

Each stage owns one auditable decision. The core never chooses or calls a model;
the caller controls provider credentials, retention, permissions, tools, and
execution. Session state preserves the task and handoff facts when that caller
changes.

For module boundaries, contracts, providers, worktrees, trust boundaries, and
the implemented-versus-roadmap matrix, read the full
[context infrastructure architecture](xirp-style-architecture.md). For usage,
see [Integrations](integrations.md) and [Sessions](sessions.md).
