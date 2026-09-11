"""Deterministic citation precheck. Pure - no I/O, no model calls, no
imports from judge.py or verify.py. `ctx` is a caller-supplied object
(built by verify.py, which has the diff/rules/lint data) exposing:
  - convention_text: str, the concatenated repo convention docs
  - test_index: set[str], every test function name in the repo
  - lint_codes_near(file, line, window=3) -> set[str], ruff codes this PR's
    own lint pass raised near that location
"""
from __future__ import annotations

import re
from enum import Enum

_QUOTE_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_TEST_NAME_RE = re.compile(r"\btest_[A-Za-z0-9_]+\b")


class Precheck(Enum):
    CONFIRMED = "confirmed"      # skip the model, citation is valid
    REJECTED = "rejected"        # citation is false; strip it, keep the finding
    NEEDS_MODEL = "needs_model"


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def extract_quoted(text: str) -> str | None:
    match = _QUOTE_RE.search(text)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def extract_test_name(text: str) -> str | None:
    match = _TEST_NAME_RE.search(text)
    return match.group(0) if match else None


def precheck(finding: dict, ctx) -> Precheck:
    if finding.get("source") == "lint":
        return Precheck.CONFIRMED

    cit = (finding.get("citation") or "").strip()
    if not cit:
        return Precheck.REJECTED

    if cit.startswith("ruff:"):
        code = cit.split(":", 1)[1].strip()
        near = ctx.lint_codes_near(finding["file"], finding["line"], window=3)
        return Precheck.CONFIRMED if code in near else Precheck.REJECTED

    quote = extract_quoted(cit)
    if quote:
        hay = normalize(ctx.convention_text)
        return Precheck.CONFIRMED if normalize(quote) in hay else Precheck.REJECTED

    test_name = extract_test_name(cit)
    if test_name:
        return Precheck.CONFIRMED if test_name in ctx.test_index else Precheck.REJECTED

    return Precheck.NEEDS_MODEL
