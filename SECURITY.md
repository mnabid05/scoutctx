# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or secret-redaction bypass. Use GitHub's **Report a vulnerability** button on the repository Security tab to submit a private report.

Include the affected version, a minimal reproduction, expected behavior, and potential impact. You should receive an acknowledgement within five business days.

## Security model

ScoutCTX's core reads local repositories and makes no outbound network requests. It can write context to stdout, a user-selected file, or its local session store. Optional HTTP and MCP adapters expose the same core to local clients; their requested roots are confined beneath the root pinned by the launcher. ScoutCTX skips symlinks and binary files, bounds per-file reads, and redacts common secret formats by default.

The development HTTP server has no authentication, authorization, or TLS. It defaults to loopback and must not be exposed directly to an untrusted network. MCP inherits the permissions of the process that launches it. A session worktree isolates Git files and indexes, but a launched harness still has the operating-system permissions of the user running it.

Redaction is defense in depth, not a guarantee that every credential or sensitive value will be detected. Review generated briefs before sending them to an external service. Disabling redaction with `--no-redact` is an explicit trust decision.

Only the latest released minor version receives security fixes while the project is in `0.x` development.
