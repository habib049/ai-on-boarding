"""Severity taxonomy and ruff-code mapping. Pure - no I/O, no model calls,
no imports from judge.py or verify.py.
"""
from __future__ import annotations

RUFF_SEVERITY = {
    "S": "CRITICAL",     # bandit / security
    "F82": "MAJOR",       # undefined name
    "F81": "MAJOR",       # redefinition
    "B": "MAJOR",         # bugbear
    "F": "MINOR",         # remaining pyflakes (F401 etc.)
    "E": "MINOR", "W": "MINOR", "I": "MINOR", "N": "MINOR",
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
