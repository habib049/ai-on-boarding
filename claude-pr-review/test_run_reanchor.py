"""Tests for run.py's reanchor_changed_files() (the changed-file re-anchor
path, 3.7, that carry_forward() alone doesn't cover) and attach_metadata()
(a regression test for a real bug the live test caught: a finding whose
`snippet` was never stored made every future re-anchor attempt see an
empty target and wrongly resolve the finding regardless of whether the
code was still there). Reads real files through run._read_file, so it uses
this repo's own tree as fixture data - no network, no API key.
"""
from __future__ import annotations

import run


def test_reanchor_finds_snippet_still_present():
    # severity.py is a real, stable file in this repo - use a line from it.
    content = (run.REPO_ROOT / "claude-pr-review/severity.py").read_text()
    line_no = next(i for i, line in enumerate(content.splitlines(), 1) if "RANK = " in line)
    prior_state = {
        "findings": [
            {"fp": "aaaa1111bbbb2222", "status": "open", "file": "claude-pr-review/severity.py",
             "line": line_no, "snippet": "RANK = {"},
        ]
    }
    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged=set())
    assert resolved == []
    assert len(re_anchored) == 1
    assert re_anchored[0]["status"] == "open"


def test_reanchor_marks_resolved_when_snippet_is_gone():
    prior_state = {
        "findings": [
            {"fp": "aaaa1111bbbb2222", "status": "open", "file": "claude-pr-review/severity.py",
             "line": 1, "snippet": "this text will never appear in severity.py"},
        ]
    }
    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged=set())
    assert re_anchored == []
    assert len(resolved) == 1
    assert resolved[0]["status"] == "resolved"


def test_reanchor_marks_resolved_when_file_deleted():
    prior_state = {
        "findings": [
            {"fp": "aaaa1111bbbb2222", "status": "open", "file": "claude-pr-review/this_file_does_not_exist.py",
             "line": 1, "snippet": "anything"},
        ]
    }
    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged=set())
    assert re_anchored == []
    assert resolved[0]["status"] == "resolved"


def test_reanchor_skips_findings_on_unchanged_files():
    prior_state = {
        "findings": [
            {"fp": "aaaa1111bbbb2222", "status": "open", "file": "claude-pr-review/severity.py",
             "line": 1, "snippet": "anything"},
        ]
    }
    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged={"claude-pr-review/severity.py"})
    assert re_anchored == []
    assert resolved == []


def test_reanchor_skips_dismissed_findings():
    prior_state = {
        "findings": [
            {"fp": "aaaa1111bbbb2222", "status": "dismissed", "file": "claude-pr-review/severity.py",
             "line": 1, "snippet": "RANK = {"},
        ]
    }
    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged=set())
    assert re_anchored == []
    assert resolved == []


def test_reanchor_cold_start_on_missing_prior_state():
    re_anchored, resolved = run.reanchor_changed_files(None, unchanged=set())
    assert re_anchored == []
    assert resolved == []


def test_attach_metadata_stores_the_snippet_it_fingerprinted():
    finding = {"file": "claude-pr-review/severity.py", "line": 1, "severity": "MINOR",
               "citation": "x", "summary": "s"}
    [out] = run.attach_metadata([finding])
    assert out["snippet"]  # non-empty
    assert out["fp"] == run.fingerprint.fingerprint(finding, out["snippet"])


def test_attach_metadata_snippet_lets_a_later_push_reanchor_correctly():
    # Regression for the bug the live test caught: without storing the
    # snippet, state.resolve() always saw an empty target and marked the
    # finding resolved even though the code was still right there.
    finding = {"file": "claude-pr-review/severity.py", "line": 1, "severity": "MINOR",
               "citation": "x", "summary": "s"}
    [with_metadata] = run.attach_metadata([finding])
    prior_state = {"findings": [{**with_metadata, "status": "open"}]}

    re_anchored, resolved = run.reanchor_changed_files(prior_state, unchanged=set())
    assert resolved == []
    assert len(re_anchored) == 1


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
