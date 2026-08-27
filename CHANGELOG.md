# Changelog

All notable changes to ScoutCTX will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-27

### Added

- Framework-neutral `build_context`, reusable `ScoutCTX`, and versioned `ContextResult` APIs.
- Persistent sessions with durable notes, deterministic IDs, archive state, and optional isolated Git worktrees.
- Safe universal harness launching with context placeholders and `SCOUTCTX_*` environment variables.
- Dependency-free HTTP and modern/legacy MCP adapters, including persistent-session context over MCP.
- Pluggable, failure-isolated organizational-context providers with bounded directory and static implementations.
- Architecture, session, integration, and LangGraph documentation.

### Changed

- Repositioned ScoutCTX from a one-shot brief CLI to a model-neutral context plane.
- Added explicit `build` and `session` commands while preserving the original `scoutctx TASK` shorthand.
- Excluded `.scoutctx/` operational state from repository scans by default.

### Security

- Confined HTTP and MCP root selection beneath the repository root pinned by the launcher.
- Sanitized persisted session notes and command history and kept child environments out of launch plans.

## [0.1.0] - 2026-08-26

### Added

- Task-aware ranking using path, content, project-anchor, and Git working-set signals.
- Token-budgeted Markdown briefs and versioned JSON output.
- Relevant line-window extraction for oversized files.
- Default redaction for credential assignments, private keys, and common token formats.
- Git-aware discovery with filesystem fallback, ignore patterns, binary detection, and symlink exclusion.
- Project configuration through `.scoutctx.toml` and `scoutctx init`.
- Zero-runtime-dependency Python CLI with an initial cross-platform test suite.

[Unreleased]: https://github.com/mnabid05/scoutctx/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mnabid05/scoutctx/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mnabid05/scoutctx/releases/tag/v0.1.0
