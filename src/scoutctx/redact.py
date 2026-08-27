"""Conservative secret redaction before repository content leaves stdout."""

from __future__ import annotations

import re


REDACTED = "<REDACTED_BY_SCOUTCTX>"

_ASSIGNMENT = re.compile(
    r"(?im)^(?P<prefix>\s*(?:export\s+)?[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET)[A-Z0-9_]*\s*[:=]\s*)"
    r"(?:(?P<quote>['\"])(?P<quoted>[^\n]*?)(?P=quote)|(?P<plain>[A-Za-z0-9_./+=:@-]{4,}))"
    r"(?P<suffix>\s*(?:[,;#].*)?)$"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.DOTALL,
)
_TOKEN_PATTERNS = [
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
]


def redact_secrets(text: str) -> tuple[str, int]:
    """Return redacted text and the number of replacements made."""

    replacements = 0

    def assignment_replacement(match: re.Match[str]) -> str:
        nonlocal replacements
        replacements += 1
        quote = match.group("quote") or ""
        return f"{match.group('prefix')}{quote}{REDACTED}{quote}{match.group('suffix')}"

    def whole_replacement(match: re.Match[str]) -> str:
        nonlocal replacements
        replacements += 1
        return REDACTED

    text = _PRIVATE_KEY.sub(whole_replacement, text)
    text = _ASSIGNMENT.sub(assignment_replacement, text)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(whole_replacement, text)
    return text, replacements
