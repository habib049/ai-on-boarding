"""Round-trip, corrupt-input, dismissal, carry-forward, and re-anchoring
tests for state.py, written before the implementation per the Phase 3 plan.
Pure - no I/O, no network. Corrupt or missing state must always degrade to
a cold start - there is no path where bad state fails the job.
"""
from __future__ import annotations

import state


def _sample_state():
    return {
        "schema": 1,
        "head": "abc123",
        "files": {"src/api/views.py": "blob1", "tests/test_api.py": "blob2"},
        "findings": [
            {"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MAJOR",
             "file": "src/api/views.py", "line": 42, "first_seen": "def456", "verified": True},
        ],
    }


# --- 3.3: render/parse round-trip ---

def test_render_parse_round_trip():
    original = _sample_state()
    comment_body = "some human text\n" + state.render(original) + "\nmore text"
    parsed = state.parse(comment_body)
    assert parsed == original


def test_parse_returns_none_when_marker_absent():
    assert state.parse("just a normal PR comment, no state here") is None


def test_parse_corrupt_json_inside_marker_degrades_to_cold_start():
    corrupt = f"<!-- {state.MARKER}\nthis is not valid json {{{{\n-->"
    assert state.parse(corrupt) is None


def test_parse_truncated_marker_degrades_to_cold_start():
    truncated = f"<!-- {state.MARKER}\n{{\"schema\": 1, \"findings\": ["
    assert state.parse(truncated) is None


def test_parse_empty_comment_degrades_to_cold_start():
    assert state.parse("") is None


# --- 3.6: dismissal ---

def test_apply_dismissals_marks_ticked_finding_dismissed():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open"}]
    comment_body = "- [x] `a1b2c3d4` MINOR `a.py:1` - some nit"
    result = state.apply_dismissals(comment_body, findings)
    assert result[0]["status"] == "dismissed"


def test_apply_dismissals_leaves_unticked_finding_open():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open"}]
    comment_body = "- [ ] `a1b2c3d4` MINOR `a.py:1` - some nit"
    result = state.apply_dismissals(comment_body, findings)
    assert result[0]["status"] == "open"


def test_apply_dismissals_ignores_unrelated_checkboxes():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open"}]
    comment_body = "- [x] some unrelated checklist item with no short id"
    result = state.apply_dismissals(comment_body, findings)
    assert result[0]["status"] == "open"


def test_render_preserves_dismissed_tick():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "dismissed", "severity": "MINOR",
                 "file": "a.py", "line": 1, "summary": "a nit"}]
    rendered = state.render_dismissal_line(findings[0])
    assert rendered.startswith("- [x]")


def test_render_open_finding_unticked():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR",
                 "file": "a.py", "line": 1, "summary": "a nit"}]
    rendered = state.render_dismissal_line(findings[0])
    assert rendered.startswith("- [ ]")


# --- 3.5: carry-forward by blob SHA ---

def test_carry_forward_keeps_open_findings_on_unchanged_files():
    prior = _sample_state()
    current_blobs = {"src/api/views.py": "blob1", "tests/test_api.py": "blob2"}
    carried, unchanged = state.carry_forward(prior, current_blobs)
    assert unchanged == {"src/api/views.py", "tests/test_api.py"}
    assert len(carried) == 1
    assert carried[0]["fp"] == "a1b2c3d4e5f6a1b2"


def test_carry_forward_drops_findings_on_changed_files():
    prior = _sample_state()
    current_blobs = {"src/api/views.py": "blob1-CHANGED", "tests/test_api.py": "blob2"}
    carried, unchanged = state.carry_forward(prior, current_blobs)
    assert unchanged == {"tests/test_api.py"}
    assert carried == []  # the one finding lived in the changed file


def test_carry_forward_drops_findings_on_removed_files():
    prior = _sample_state()
    current_blobs = {"tests/test_api.py": "blob2"}  # views.py deleted
    carried, unchanged = state.carry_forward(prior, current_blobs)
    assert carried == []


def test_carry_forward_ignores_dismissed_and_resolved_findings():
    prior = _sample_state()
    prior["findings"][0]["status"] = "dismissed"
    current_blobs = {"src/api/views.py": "blob1", "tests/test_api.py": "blob2"}
    carried, _ = state.carry_forward(prior, current_blobs)
    assert carried == []


def test_carry_forward_cold_start_on_missing_prior_state():
    carried, unchanged = state.carry_forward(None, {"a.py": "blob1"})
    assert carried == []
    assert unchanged == set()


# --- 3.7: resolution / re-anchoring ---

def test_resolve_finds_snippet_at_recorded_line():
    entry = {"line": 3, "snippet": "def foo(): return 1"}
    new_content = "x = 1\ny = 2\ndef foo(): return 1\nz = 3"
    status, new_line = state.resolve(entry, new_content)
    assert status == "open"
    assert new_line == 3


def test_resolve_reanchors_when_snippet_shifted_within_window():
    entry = {"line": 3, "snippet": "def foo(): return 1"}
    new_content = "\n".join(["pad"] * 10 + ["def foo(): return 1"])
    status, new_line = state.resolve(entry, new_content)
    assert status == "open"
    assert new_line == 11


def test_resolve_marks_resolved_when_snippet_is_gone():
    entry = {"line": 3, "snippet": "def foo(): return 1"}
    new_content = "completely different file\nwith no trace of it"
    status, new_line = state.resolve(entry, new_content)
    assert status == "resolved"
    assert new_line is None


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
