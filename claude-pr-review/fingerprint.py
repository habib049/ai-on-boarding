"""Content-addressed finding identity, so a finding the author already
answered can be recognized across pushes even as line numbers drift. Pure -
no I/O, no model calls.

No line number in the key deliberately: a line number shifts when anything
above it changes, and a fingerprint that changes on every unrelated edit is
not a fingerprint. `line` is carried alongside as a re-anchoring hint (see
state.py's resolve()), never part of the identity itself.
"""
from __future__ import annotations

import hashlib
import re

_COMMENT_RE = re.compile(r"#.*$", re.M)


def normalize_snippet(s: str) -> str:
    s = _COMMENT_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def fingerprint(finding: dict, snippet: str) -> str:
    key = "|".join([
        finding.get("source") or "model",
        finding["file"],
        finding.get("category") or finding.get("citation") or "",
        normalize_snippet(snippet),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def short_id(fp: str) -> str:
    """First 8 chars, shown to humans (dismissal checkboxes, comment text)."""
    return fp[:8]
