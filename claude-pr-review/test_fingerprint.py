"""Round-trip and stability tests for fingerprint.py, written before the
implementation per the Phase 3 plan. Pure - no I/O, no network.
"""
from __future__ import annotations

import fingerprint


def _finding(file="a.py", citation="c", source=None, category=None):
    f = {"file": file, "citation": citation}
    if source:
        f["source"] = source
    if category:
        f["category"] = category
    return f


def test_same_finding_and_snippet_same_fingerprint():
    f1 = fingerprint.fingerprint(_finding(), "def foo(): pass")
    f2 = fingerprint.fingerprint(_finding(), "def foo(): pass")
    assert f1 == f2


def test_different_file_different_fingerprint():
    f1 = fingerprint.fingerprint(_finding(file="a.py"), "snippet")
    f2 = fingerprint.fingerprint(_finding(file="b.py"), "snippet")
    assert f1 != f2


def test_different_citation_different_fingerprint():
    f1 = fingerprint.fingerprint(_finding(citation="c1"), "snippet")
    f2 = fingerprint.fingerprint(_finding(citation="c2"), "snippet")
    assert f1 != f2


def test_fingerprint_survives_comment_only_edits():
    # A comment added above the snippet, or trailing whitespace, must not
    # change the fingerprint - otherwise every unrelated edit above a
    # finding re-raises it as "new".
    f1 = fingerprint.fingerprint(_finding(), "def foo():\n    return 1")
    f2 = fingerprint.fingerprint(_finding(), "def foo():  # now with a comment\n    return 1   ")
    assert f1 == f2


def test_fingerprint_changes_when_snippet_logic_changes():
    f1 = fingerprint.fingerprint(_finding(), "def foo(): return 1")
    f2 = fingerprint.fingerprint(_finding(), "def foo(): return 2")
    assert f1 != f2


def test_fingerprint_is_16_hex_chars():
    fp = fingerprint.fingerprint(_finding(), "snippet")
    assert len(fp) == 16
    int(fp, 16)  # raises if not hex


def test_normalize_snippet_strips_comments():
    assert fingerprint.normalize_snippet("x = 1  # a comment") == "x = 1"


def test_normalize_snippet_collapses_whitespace_and_case():
    assert fingerprint.normalize_snippet("  Def   Foo(): \n  Return 1  ") == "def foo(): return 1"


def test_short_id_is_first_eight_chars():
    fp = fingerprint.fingerprint(_finding(), "snippet")
    assert fingerprint.short_id(fp) == fp[:8]
    assert len(fingerprint.short_id(fp)) == 8


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
