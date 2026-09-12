"""Severity taxonomy and ruff-code mapping. Pure - no I/O, no model calls,
no imports from judge.py or verify.py.
"""
from __future__ import annotations

# Every prefix here must be one ruff.toml actually selects, or it is a
# severity tier the linter is never asked to produce - which is what made
# `S -> CRITICAL` decoration until S was selected. test_lint_layer.py
# asserts the two stay in sync.
#
# `W` (pycodestyle warnings) and `N` (pep8-naming) are deliberately absent:
# both would map to MINOR, which is already what severity_for_ruff()
# returns for an unrecognised code, so listing them changes nothing.
RUFF_SEVERITY = {
    "S": "CRITICAL",      # bandit / security - hardcoded secrets, eval, injection
    "F82": "MAJOR",       # undefined name
    "F81": "MAJOR",       # redefinition
    "B": "MAJOR",         # bugbear
    "F": "MINOR",         # remaining pyflakes (F401 etc.)
    "E": "MINOR",
    "I": "MINOR",
}

RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


def severity_for_ruff(code: str) -> str:
    """Map a ruff rule code to a severity. Longest-prefix match: F821 must
    hit F82 before the generic F bucket.
    """
    for prefix in sorted(RUFF_SEVERITY, key=len, reverse=True):
        if code.startswith(prefix):
            return RUFF_SEVERITY[prefix]
    return "MINOR"


def max_severity(a: str, b: str) -> str:
    return a if RANK[a] >= RANK[b] else b
