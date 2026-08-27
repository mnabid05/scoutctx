# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or secret-redaction bypass. Use GitHub's **Report a vulnerability** button on the repository Security tab to submit a private report.

Include the affected version, a minimal reproduction, expected behavior, and potential impact. You should receive an acknowledgement within five business days.

## Security model

ScoutCTX reads local repositories and writes their content to stdout or a user-selected file. It makes no network requests. It skips symlinks and binary files, bounds per-file reads, and redacts common secret formats by default.

Redaction is defense in depth, not a guarantee that every credential or sensitive value will be detected. Review generated briefs before sending them to an external service. Disabling redaction with `--no-redact` is an explicit trust decision.

Only the latest released minor version receives security fixes while the project is in `0.x` development.

