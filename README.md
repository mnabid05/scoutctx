<div align="center">
  <img src="assets/hero.svg" alt="ScoutCTX — signal for your coding agent" width="100%" />

  <p><strong>Give your coding agent the right files, not the whole repository.</strong></p>

  <p>
    <a href="https://github.com/mnabid05/scoutctx/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/mnabid05/scoutctx/ci.yml?branch=main&style=flat-square&label=tests"></a>
    <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-6ee7b7?style=flat-square"></a>
    <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-93c5fd?style=flat-square">
    <img alt="Zero runtime dependencies" src="https://img.shields.io/badge/runtime_dependencies-0-f9a8d4?style=flat-square">
  </p>
</div>

ScoutCTX is a local-first CLI that ranks repository files against your task, fits the useful parts into a token budget, and produces a portable brief for Codex, Claude Code, Cursor, Copilot, or any other coding agent.

```bash
scoutctx "fix the flaky OAuth callback tests" --output context.md
```

No model calls. No embeddings. No account. Your code never leaves your machine.

## Why ScoutCTX?

Coding agents are only as good as the context they receive. Sending an entire repository wastes tokens and buries the files that matter; hand-picking files becomes its own chore.

ScoutCTX turns a task into a compact, reviewable context pack:

- **Task-aware:** explains why each selected file ranked highly.
- **Git-aware:** boosts files in the current working set and honors `.gitignore`.
- **Budget-aware:** extracts relevant windows from large files instead of blindly truncating the bundle.
- **Secret-aware:** redacts common credentials, private keys, and tokens by default.
- **Prompt-injection-aware:** labels repository text as untrusted data in every Markdown brief.
- **Agent-agnostic:** emits plain Markdown or versioned JSON.
- **Fast and offline:** uses the Python standard library and Git—nothing else at runtime.

## Quick start

Install directly from GitHub with your preferred tool:

```bash
pipx install git+https://github.com/mnabid05/scoutctx.git
# or
uv tool install git+https://github.com/mnabid05/scoutctx.git
```

Then scout from any repository:

```bash
cd your-project
scoutctx "add rate limiting to the public API" --output context.md
```

Attach `context.md` to your agent, paste it into a chat, or pipe it into another tool. ScoutCTX also works well as a quick orientation pass:

```bash
scoutctx | less
```

## What the brief contains

```text
ScoutCTX brief
├── task and token budget
├── compact repository map
├── current Git working set
└── ranked file excerpts
    ├── score
    ├── selection reasons
    └── task-centered content
```

Selection is intentionally transparent. A file might say `changed in Git; path: auth; content: callback`, so you can see why it made the cut instead of trusting a black box.

## Useful recipes

### Fit a smaller context window

```bash
scoutctx "trace the payment webhook" --budget 4000
```

### Focus on a package

```bash
scoutctx "remove the deprecated API" --include "packages/core/**"
```

### Leave out generated or noisy files

```bash
scoutctx "simplify the dashboard" \
  --exclude "**/*.generated.ts" \
  --exclude "apps/legacy/**"
```

### Feed structured context to another tool

```bash
scoutctx "review session handling" --format json --output context.json
```

### Scan a directory without Git

```bash
scoutctx "understand this prototype" --no-git --root ../prototype
```

## Project configuration

Run `scoutctx init` to create a documented `.scoutctx.toml`:

```toml
[scoutctx]
budget = 12000
max_file_bytes = 262144
max_files = 24
redact = true

include = []
exclude = ["*.min.js", "*.map", "coverage/**", "fixtures/**"]
```

For project-specific exclusions, add a `.scoutctxignore` file. Command-line flags extend the configured `include` and `exclude` lists.

## How ranking works

ScoutCTX uses a small, deterministic scoring pipeline:

1. Extract meaningful terms from the task.
2. Score path matches, content matches, project anchors, and Git changes.
3. Prefer compact high-signal files when scores tie.
4. Extract line windows around task terms for oversized files.
5. Redact secrets, then assemble the brief within the requested budget.

There is no hidden network request and no index to keep fresh. Run the same command against the same working tree and you get the same brief.

## Security notes

Redaction is a safety net, not a formal secret scanner. Always review a brief before sharing it outside your machine. ScoutCTX skips binary files and symlinks, caps the bytes read from any one file, and enables redaction by default. Use `--no-redact` only for a destination you trust.

Please report suspected vulnerabilities through the process in [SECURITY.md](SECURITY.md).

## Development

```bash
git clone https://github.com/mnabid05/scoutctx.git
cd scoutctx
python -m pip install -e .
python -m unittest discover -s tests -v
```

The project deliberately keeps its runtime dependency count at zero. See [CONTRIBUTING.md](CONTRIBUTING.md) for the design guardrails and contribution workflow.

## Roadmap

- Language-aware symbol boundaries for even sharper excerpts
- Optional `stdin` mode for issue and pull-request descriptions
- Shareable ranking profiles for monorepos
- MCP resource adapter without changing the offline-first core

If ScoutCTX saves you from another 80,000-token repository dump, consider starring the project—it helps other agent builders find it.

## License

[MIT](LICENSE) © ScoutCTX contributors
