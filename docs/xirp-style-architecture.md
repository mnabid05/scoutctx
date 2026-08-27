# ScoutCTX architecture: open context infrastructure

ScoutCTX is a vendor-neutral context and session layer for coding agents. It
keeps repository discovery, task context, and durable session knowledge outside
any one model or agent harness. A developer can build one context package and
give it to a hosted model, a local model, an editor, or an orchestration
framework without changing the core.

The project takes inspiration from the broader move toward portable agent
workspaces described in [Spotify's public Xirp
introduction](https://portal.spotify.com/blog/introducing-xirp), while defining
its own small, auditable, open-source architecture.

## Status at a glance

The labels below distinguish code that exists now from the direction of the
project.

| Capability | Status |
| --- | --- |
| Task-aware repository scanning, ranking, excerpts, and token budgets | Implemented |
| Secret redaction by default and bounded local file reads | Implemented |
| Markdown and JSON context packages | Implemented |
| CLI and framework-neutral Python API | Implemented |
| Local HTTP and stdio MCP adapters | Implemented |
| Persistent sessions, shared notes, and optional Git worktrees | Implemented |
| Run an installed harness inside a session and record the invocation | Implemented |
| Context-provider protocol, registry, and bounded directory provider | Implemented |
| Named harness profiles and automatic plugin discovery | Roadmap |
| Remote workers, team synchronization, catalog connectors, and web UI | Roadmap |

## Design principles

1. **Context belongs to the task.** A model invocation consumes context; it
   does not own it. The durable task, notes, selected code, and worktree stay
   useful when the developer changes models.
2. **Harnesses stay replaceable.** ScoutCTX runs or feeds external tools; it
   does not reimplement their agent loops or require their SDKs.
3. **Local behavior is the baseline.** Scanning, ranking, redaction, sessions,
   MCP, and HTTP work with the Python standard library and no runtime packages.
4. **Determinism makes context reviewable.** Given the same task, repository,
   and options, context ordering and rendering do not depend on timestamps,
   random identifiers, or a model call.
5. **Repository content is untrusted.** Source text may include malicious
   instructions. It is quoted as data, redacted where possible, and must not be
   treated as control-plane policy.
6. **The user remains the authority.** ScoutCTX supplies context and process
   isolation. A connected agent still needs its own permission, review, and
   execution policy.

## System model

```text
 repository + task + config + session notes
                    |
                    v
       scan -> rank -> excerpt -> redact -> budget
                    |
                    v
          ContextResult (Markdown or JSON)
             /          |           \
        Python API     HTTP         MCP
             \          |           /
              model SDK / agent harness
                         |
                  session worktree
```

ScoutCTX has a model-free core and thin transport adapters:

- `scanner.py`, `git.py`, and `config.py` discover eligible repository files
  and Git state without following symlinks.
- `ranking.py` scores candidates against the task and gives useful weight to
  the active Git working set.
- `brief.py`, `redact.py`, and `render.py` choose bounded excerpts, remove
  common credential patterns, enforce the output budget, and render a portable
  package.
- `framework.py` exposes `build_context`, `ScoutCTX`, and the versioned
  `ContextResult` envelope used by every integration.
- `providers.py` defines the small plugin contract for adding institutional
  knowledge, plus deterministic collection, failure isolation, and bounded
  local directory and static providers.
- `sessions.py` persists task continuity, notes, harness history, and optional
  worktree coordinates below `.scoutctx/`.
- `harness.py` builds a fresh session snapshot and launches any command as an
  argument vector in the session worktree, without invoking a shell.
- `http.py` and `mcp.py` translate their protocols into the same Python API.
  They do not contain separate ranking or retrieval logic.
- `cli.py` is the human-facing dispatcher for builds, sessions, and adapters.

This separation matters: a transport integration cannot silently change the
ranking algorithm, and an improvement to context selection reaches every
integration at once.

## Context contract

The smallest stable exchange type is `ContextResult`:

```python
from scoutctx.framework import build_context

result = build_context(
    "fix the retry race in the worker",
    root="/path/to/repository",
    budget=4_000,
)

prompt_context = result.content
audit_metadata = result.metadata
portable_envelope = result.to_dict()
```

`content` is the payload intended for an agent or model. `metadata` describes
the task, repository name, selected files, approximate token use, and redaction
state without exposing a machine-specific repository path. `to_dict()` adds a
schema version for transport and storage.

The command-line equivalent is:

```bash
scoutctx build "fix the retry race in the worker" \
  --budget 4000 \
  --output context.md
```

For compatibility, `scoutctx "task"` maps to `scoutctx build "task"`.

## Sessions and worktrees

A session binds a durable task to an isolated working directory and shared
notes. By default, starting a session in Git creates both a
`scoutctx/<session-id>` branch and a linked worktree under
`.scoutctx/worktrees/`. Concurrent harnesses can therefore work on the same
repository without sharing an index or overwriting one another's files.

```bash
scoutctx session start "replace the legacy retry policy"
scoutctx session list
scoutctx session note replace-the-legacy-retry-policy-01 \
  "Keep the public Worker constructor backward compatible."
scoutctx session context replace-the-legacy-retry-policy-01 \
  --output context.md
scoutctx session run replace-the-legacy-retry-policy-01 -- \
  my-agent --context-file '{context}'
```

The session record stores the task, relative worktree, branch, redacted notes,
harness names, and a sanitized copy of invoked argument vectors. It
intentionally does not capture process environment variables, model
credentials, or a full terminal transcript. See [Sessions](sessions.md) for the
lifecycle and recovery model.

## Context providers

The implemented `ContextProvider` protocol lets an integration add curated
documentation, architecture decisions, ownership data, or other institutional
knowledge to the repository brief:

```python
from scoutctx.framework import build_context
from scoutctx.providers import DirectoryProvider, ProviderRegistry

providers = ProviderRegistry({
    "team-docs": DirectoryProvider(
        "docs/decisions",
        globs=("**/*.md",),
        source="team-docs",
        weight=10,
    )
})

result = build_context(
    "change token refresh behavior",
    root="/path/to/repository",
    providers=providers,
)
```

Providers receive an immutable task, repository root, and budget request, then
return `ContextDocument` objects. The registry orders documents
deterministically, rejects duplicate IDs, and converts a failing plugin into a
diagnostic so other providers still contribute. Provider content is excerpted,
budgeted, and redacted before it enters the result.

`DirectoryProvider` is constrained below the requested root, ignores symlinks
and binary-looking data, and enforces per-file, total-byte, and file-count
limits. `StaticProvider` is useful for application-owned policies or tests.
Automatic package discovery and remote catalog connectors remain roadmap work;
applications register providers explicitly today.

## Harness boundary

Today, `session run` is the universal harness adapter: anything available as a
local command can participate. That includes Codex, Claude Code, Gemini CLI,
local inference tools, scripts, and team-specific wrappers. The harness receives
the session working directory and remains responsible for its own model calls,
tools, permissions, and conversation state.

The harness-profile roadmap will formalize this boundary without adding model
logic to the core. A profile should be able to declare:

- a stable name and the executable or SDK it targets;
- how ScoutCTX content is delivered (argument, file, stdin, or API message);
- optional capability metadata such as streaming or structured context;
- preflight validation and an invocation plan; and
- sanitized run metadata returned to the session store.

Plugins must not receive credentials from ScoutCTX storage. Providers continue
to use their native credential mechanisms, and an invocation record must remain
safe to persist.

## Integration surfaces

The same operation is available through four supported surfaces:

| Surface | Best for | Entry point |
| --- | --- | --- |
| CLI | Humans, scripts, and local harnesses | `scoutctx build` |
| Python | SDKs, notebooks, and orchestration frameworks | `build_context(...)` |
| HTTP | Language-independent local services | `POST /v1/context` |
| MCP | Agent clients with dynamic tool use | `scout_context`, `scout_session_context` |

See [Integrations](integrations.md) for complete examples.

## Trust boundaries

### Repository plane

Repository files, filenames, diffs, and configuration-controlled include
patterns are data. They may contain prompt injections or secrets. ScoutCTX
excludes symlinks, bounds per-file reads, honors repository filters, and redacts
common secret shapes by default. Redaction is a safety net rather than a proof
that a payload is secret-free; review context before sending it outside the
machine.

### Session plane

`.scoutctx/sessions/` contains plaintext task descriptions, shared notes,
relative worktree coordinates, and command arguments. Do not put credentials in
tasks, notes, or command-line arguments. Archive hides a session from the
default list but deliberately preserves its state; it is not deletion.

### Process plane

`session run` executes a program with the developer's operating-system
permissions. ScoutCTX isolation prevents Git working-copy collisions, not
malicious or unrestricted process behavior. Use the connected harness's
sandbox, approval, network, and tool policies.

### Transport plane

The MCP adapter uses stdio and inherits the launching client's permissions. MCP
and HTTP caller-selected roots are confined beneath the root configured when
the adapter starts. The HTTP adapter defaults to loopback, has a bounded request
body, and does not provide authentication or TLS. Keep it local or place an
authenticated service in front of it; never expose the development server
directly to an untrusted network.

### Model plane

No model call occurs inside the ScoutCTX core. Sending `ContextResult.content`
to a provider crosses a separate privacy boundary controlled by the calling
application. Its data-retention, training, region, and tool-execution policies
still apply.

## Roadmap boundaries

ScoutCTX is currently a local context and session framework, not a hosted agent
platform. A future remote runner, team workspace, organization catalog, or
generated knowledge base should build on the same versioned context and session
contracts. Those additions need explicit authentication, authorization,
encryption, retention, tenant isolation, audit events, and conflict semantics
before they can be considered safe for shared deployments.
