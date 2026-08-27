# Sessions

ScoutCTX sessions preserve task context independently of a model or coding
harness. A session can start with one tool, continue with another, and retain
the same task, worktree, notes, and context-generation rules.

Sessions are implemented for local repositories. Team synchronization, remote
workers, shared authorization, transcript ingestion, and generated
organizational knowledge are roadmap capabilities.

## What a session owns

Each session stores a versioned record under `.scoutctx/sessions/<id>/` with:

- the durable task;
- active or archived status;
- repository name;
- optional branch and relative worktree location;
- harness executable names;
- recorded harness argument vectors; and
- ordered shared notes.

Generating session context also persists the latest `context.md` or
`context.json` snapshot in that directory. Markdown starts with a continuity
section and then includes the usual ranked, redacted, token-budgeted repository
brief. JSON remains valid JSON and adds a top-level `session` object containing
the session ID, status, harness history, and notes.

The store does **not** intentionally capture environment variables,
credentials, provider API requests, model responses, or terminal transcripts.
Those remain the responsibility of the connected harness.

## Lifecycle

```text
 start -> add notes -> build context -> run one or more harnesses -> archive
   |                        |                    |
   +--- isolated worktree --+--- shared state ---+
```

### 1. Start

From a Git repository:

```bash
scoutctx session start "replace polling with event delivery"
```

The command returns a deterministic, task-derived identifier with a numeric
suffix, such as `replace-polling-with-event-delivery-01`. By default it creates:

- branch `scoutctx/replace-polling-with-event-delivery-01`; and
- worktree `.scoutctx/worktrees/replace-polling-with-event-delivery-01`.

The numeric suffix avoids collisions without random identifiers. Session
creation uses `git worktree add -b`; it does not modify the primary working
tree's index or move its current branch.

For a non-Git directory, or when isolation is not wanted:

```bash
scoutctx session start "inventory the parser" --no-worktree
```

A no-worktree session operates in the repository root. Do not run multiple
write-capable agents there concurrently.

### 2. Inspect and list

List active sessions:

```bash
scoutctx session list
```

Include archived sessions:

```bash
scoutctx session list --all
```

Inspect one persisted record:

```bash
scoutctx session show replace-polling-with-event-delivery-01
```

Listing order is deterministic by identifier. Invalid or unsupported records
are skipped by listing rather than making every other session unavailable;
`show` surfaces the error for the selected record.

### 3. Share durable notes

Add information that every later harness should receive:

```bash
scoutctx session note replace-polling-with-event-delivery-01 \
  "The events package is public; preserve its import path."
```

Notes are best for decisions, constraints, failed approaches, and handoff facts
that are not obvious from the repository. They are plaintext and become part of
generated session context, so never put secrets in them. Common secret shapes
are redacted before a note is persisted, even if context redaction is disabled.

Notes are append-only in the current CLI. Editing, attribution, conflict
resolution, and team synchronization are roadmap work.

### 4. Build portable context

Print context to stdout:

```bash
scoutctx session context replace-polling-with-event-delivery-01 \
  --budget 6000
```

Or write a file that another tool can consume:

```bash
scoutctx session context replace-polling-with-event-delivery-01 \
  --budget 6000 \
  --output context.md
```

Context is built against the session worktree, not the primary checkout. The
snapshot therefore follows changes made by that session's harness. Task,
status, harness history, and notes are prepended to the standard repository
brief.

The usual context controls remain available, including budget, selected-file
limits, include/exclude patterns, Git discovery, redaction, output format, and
bounded reads. Redaction remains enabled unless explicitly disabled.

### 5. Run any installed harness

Use `--` to separate ScoutCTX arguments from the harness command:

```bash
scoutctx session run replace-polling-with-event-delivery-01 -- \
  codex "Implement the session task and run focused tests. Context: {context}"
```

Or run a local model wrapper:

```bash
scoutctx session run replace-polling-with-event-delivery-01 -- \
  ./tools/local-agent --model qwen --context '{context}'
```

The process runs in the session worktree and uses its native configuration and
credential mechanism. ScoutCTX records the executable name and argument vector
for continuity, but it does not store the process environment. Common secrets,
sensitive option values, and sensitive `--option=value` arguments are redacted
in the persisted copy; they are still passed unchanged to the child process.

The launcher substitutes four placeholders inside individual command
arguments: `{context}`, `{task}`, `{worktree}`, and `{session}`. It also supplies
these ScoutCTX-owned variables:

| Variable | Value |
| --- | --- |
| `SCOUTCTX_CONTEXT_FILE` | Absolute path to the generated session snapshot |
| `SCOUTCTX_CONTEXT_FORMAT` | `markdown` or `json` |
| `SCOUTCTX_SESSION_ID` | Stable local session identifier |
| `SCOUTCTX_TASK` | Durable task text |
| `SCOUTCTX_WORKTREE` | Absolute session working directory |
| `SCOUTCTX_REPOSITORY` | Repository name |

The inherited environment is passed directly to the child process but is not
shown in a dry run or saved in session metadata. Use `--dry-run` to generate the
context and inspect the expanded, sanitized launch plan without executing or
recording the harness:

```bash
scoutctx session run --dry-run \
  replace-polling-with-event-delivery-01 -- \
  my-agent --context '{context}'
```

This is the current universal harness boundary. Named harness profiles,
capability discovery, streamed run events, cancellation, and remote execution
are roadmap features.

### 6. Archive

When the handoff or change is complete:

```bash
scoutctx session archive replace-polling-with-event-delivery-01
```

Archiving changes status and hides the session from the default list. It keeps
the record, context snapshot, Git branch, and worktree so work can be inspected
or resumed. Archive is not delete, worktree removal, or branch deletion.

## Switching harnesses

There is no model-specific migration step. Rebuild the session context after
the first harness changes files or adds a useful note, then run the next
harness:

```bash
SESSION=replace-polling-with-event-delivery-01

scoutctx session context "$SESSION" --output context.md
scoutctx session run "$SESSION" -- first-agent --context '{context}'

scoutctx session note "$SESSION" \
  "First pass changed delivery.py; cancellation tests still fail."
scoutctx session context "$SESSION" --output context.md
scoutctx session run "$SESSION" -- second-agent --context '{context}'
```

`$SESSION` above is a convenience shell variable, not a ScoutCTX environment
variable. The repository state lives in the worktree; concise cross-harness
knowledge lives in notes; selected context is regenerated from both.

## Python API

Applications can manage the same lifecycle without invoking the CLI:

```python
from scoutctx.sessions import SessionManager

sessions = SessionManager("/path/to/repository")
session = sessions.start("replace polling with event delivery")
sessions.note(session.id, "Preserve the public events import path.")

context = sessions.context(session.id, budget=6_000)
print(context.content)

sessions.record_run(session.id, ["my-agent", "--context", "context.md"])
sessions.archive(session.id)
```

`record_run` records an invocation; it does not execute it. The CLI's `session
run` command combines process execution with session recording.

## Storage and recovery

Session metadata is JSON with sorted keys and a schema version. Updates use a
temporary file followed by replacement so readers do not normally observe a
partially written record. Identifiers accept only lowercase letters, digits,
and hyphens, and worktree paths must remain under `.scoutctx/worktrees/`.

The `.scoutctx/` directory is local operational state. Decide explicitly
whether to ignore, back up, or synchronize it for your environment. Blindly
committing it can leak task descriptions, notes, command arguments, or selected
source excerpts.

If a session worktree is moved or removed outside ScoutCTX, context generation
and harness execution fail safely instead of falling back to another directory.
Use `git worktree list` to inspect Git's view, repair or prune it with normal Git
commands, and keep the session JSON only if its continuity remains useful.

## Concurrency model

Worktrees isolate Git indexes and files, so separate sessions can safely work on
different branches of the same repository. They do not solve every concurrency
problem:

- two processes inside the same session still share one working tree;
- services, ports, caches, databases, and build output outside the worktree may
  still collide;
- Git branch integration and merge conflicts still require coordination; and
- session JSON has atomic replacement but no multi-writer transaction or lock.

Use one write-capable harness at a time per session. Give each concurrent task
its own session and worktree.

## Security and privacy

- Repository content is untrusted, even when it is included in a context
  package. Keep task instructions separate and preserve the injection warning.
- Redaction covers common secret shapes but cannot prove that all sensitive
  data was removed. Review before sending context to an external provider.
- Tasks, notes, context snapshots, and command arguments are plaintext local
  files. Notes and recorded commands receive common-pattern redaction, but do
  not rely on it as credential storage; keep secrets out of persisted fields.
- A harness runs with the launching user's operating-system permissions.
  Worktree isolation is not a process sandbox.
- Session identifiers are validated and worktrees are constrained below the
  ScoutCTX state directory, limiting path traversal and accidental writes.
- Archive preserves data. Apply your own retention and secure-deletion policy
  when local session state must be removed.

## Roadmap

The local session format is the base for future collaboration, but the
following are not implemented yet:

- provider and harness plugin discovery;
- live logs, structured run events, cancellation, retry, and cost metadata;
- remote workers and queued background runs;
- multi-user ownership, authentication, role-based access, and session locks;
- encrypted or server-backed session storage;
- synchronized team notes and conflict resolution;
- catalog, issue tracker, documentation, and ownership connectors; and
- transcript-to-knowledge workflows with review and retention controls.

Those features must preserve the core rule: a session's useful context remains
portable when the model, harness, or execution location changes.
