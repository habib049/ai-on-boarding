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


def test_parse_valid_json_that_is_a_list_degrades_to_cold_start():
    # Valid JSON, wrong shape. Callers do .get() on the result, so handing
    # this back would turn a mangled comment into an AttributeError that
    # fails the job - the exact opposite of the cold-start rule.
    assert state.parse(f"<!-- {state.MARKER}\n[1, 2, 3]\n-->") is None


def test_parse_valid_json_that_is_a_string_degrades_to_cold_start():
    assert state.parse(f'<!-- {state.MARKER}\n"just a string"\n-->') is None


def test_parse_json_null_degrades_to_cold_start():
    assert state.parse(f"<!-- {state.MARKER}\nnull\n-->") is None


def test_parse_empty_object_is_valid_state_not_a_cold_start():
    # An empty object is a legitimate (if contentless) state block; it must
    # be distinguishable from "no state at all".
    assert state.parse(f"<!-- {state.MARKER}\n{{}}\n-->") == {}


def test_parse_ignores_a_marker_that_is_not_ours():
    assert state.parse("<!-- some-other-tool:state:v1\n{}\n-->") is None


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


def test_apply_dismissals_tolerates_a_finding_without_a_fingerprint():
    # No fingerprint means no identity a tick could name - pass it through
    # rather than crashing the whole run on a KeyError.
    findings = [{"status": "open", "summary": "no fp here"}]
    result = state.apply_dismissals("- [x] `a1b2c3d4` whatever", findings)
    assert result[0]["status"] == "open"


def test_apply_dismissals_matches_case_insensitively():
    findings = [{"fp": "A1B2C3D4E5F6A1B2", "status": "open"}]
    result = state.apply_dismissals("- [x] `a1b2c3d4` MINOR `a.py:1` - x", findings)
    assert result[0]["status"] == "dismissed"


def test_apply_dismissals_does_not_mutate_the_input():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open"}]
    state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert findings[0]["status"] == "open"


def test_apply_dismissals_only_matches_the_exact_short_id():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open"}]
    result = state.apply_dismissals("- [x] `a1b2c3d5` a different finding", findings)
    assert result[0]["status"] == "open"


def test_unticking_a_dismissed_finding_raises_it_again():
    # The agent always renders a dismissed finding as `- [x]`, so a `- [ ]`
    # line for one can only have come from a person clearing it.
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "dismissed", "severity": "MINOR",
                 "dismissed_at_severity": "MINOR"}]
    [out] = state.apply_dismissals("- [ ] `a1b2c3d4` MINOR `a.py:1` - x", findings)
    assert out["status"] == "open"
    assert "dismissed_at_severity" not in out


def test_unticked_open_finding_simply_stays_open():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR"}]
    [out] = state.apply_dismissals("- [ ] `a1b2c3d4` MINOR `a.py:1` - x", findings)
    assert out["status"] == "open"


def test_an_id_both_ticked_and_unticked_resolves_toward_showing_it():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR"}]
    body = "- [x] `a1b2c3d4` x\n- [ ] `a1b2c3d4` x"
    [out] = state.apply_dismissals(body, findings)
    assert out["status"] == "open"


def test_apply_dismissals_records_the_severity_that_was_waived():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR"}]
    [out] = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert out["dismissed_at_severity"] == "MINOR"


def test_apply_dismissals_refuses_a_stale_tick_on_an_escalated_finding():
    # The `- [x]` line is still in the comment from when this was a nit,
    # but the finding is now CRITICAL. Re-applying the tick would suppress
    # a security finding because someone waved off a style nit.
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "CRITICAL",
                 "dismissed_at_severity": "MINOR"}]
    [out] = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert out["status"] == "open"
    assert out["resurfaced"] is True


def test_apply_dismissals_resurfaces_an_already_dismissed_escalation():
    # Even if nothing else flipped it first, a dismissed entry whose
    # severity now exceeds what was waived must come back open - this
    # function can't rely on dedupe_findings() having run.
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "dismissed", "severity": "CRITICAL",
                 "dismissed_at_severity": "MINOR"}]
    [out] = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert out["status"] == "open"
    assert out["resurfaced"] is True


def test_apply_dismissals_honours_a_tick_at_the_same_severity():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR",
                 "dismissed_at_severity": "MINOR"}]
    [out] = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert out["status"] == "dismissed"


def test_apply_dismissals_honours_a_tick_when_severity_dropped():
    findings = [{"fp": "a1b2c3d4e5f6a1b2", "status": "open", "severity": "MINOR",
                 "dismissed_at_severity": "MAJOR"}]
    [out] = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert out["status"] == "dismissed"


def test_apply_dismissals_dismisses_every_entry_sharing_the_fingerprint():
    # Same finding arriving from two sources on one push: one tick covers
    # both, because the tick names an identity, not a list position.
    findings = [
        {"fp": "a1b2c3d4e5f6a1b2", "status": "open", "summary": "carried"},
        {"fp": "a1b2c3d4e5f6a1b2", "status": "open", "summary": "fresh"},
    ]
    result = state.apply_dismissals("- [x] `a1b2c3d4` x", findings)
    assert [f["status"] for f in result] == ["dismissed", "dismissed"]


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


def test_carry_forward_tolerates_state_without_a_files_key():
    carried, unchanged = state.carry_forward({"findings": []}, {"a.py": "blob1"})
    assert carried == []
    assert unchanged == set()


def test_carry_forward_tolerates_state_without_a_findings_key():
    carried, unchanged = state.carry_forward({"files": {"a.py": "blob1"}}, {"a.py": "blob1"})
    assert carried == []
    assert unchanged == {"a.py"}


def test_carry_forward_ignores_a_new_file_absent_from_prior_state():
    prior = _sample_state()
    carried, unchanged = state.carry_forward(prior, {"brand/new.py": "blobX"})
    assert "brand/new.py" not in unchanged
    assert carried == []


# --- 3.6: dismissals are durable state, not just rendered text ---

def test_carried_dismissals_returns_dismissed_findings():
    prior = _sample_state()
    prior["findings"][0]["status"] = "dismissed"
    assert len(state.carried_dismissals(prior)) == 1


def test_carried_dismissals_excludes_open_and_resolved():
    prior = _sample_state()
    prior["findings"] = [
        {"fp": "1", "status": "open"},
        {"fp": "2", "status": "resolved"},
        {"fp": "3", "status": "dismissed"},
    ]
    assert [f["fp"] for f in state.carried_dismissals(prior)] == ["3"]


def test_carried_dismissals_survives_even_when_the_file_changed():
    # A dismissal is keyed to a fingerprint, not to a file being untouched.
    # If the code changed materially the fingerprint changes with it and the
    # finding legitimately comes back as new - that's the only way a
    # dismissal should stop applying.
    prior = _sample_state()
    prior["findings"][0]["status"] = "dismissed"
    carried, _ = state.carry_forward(prior, {"src/api/views.py": "COMPLETELY-DIFFERENT-BLOB"})
    assert carried == []                              # not carried as open
    assert len(state.carried_dismissals(prior)) == 1  # but the dismissal stands


def test_carried_dismissals_cold_start_on_missing_prior_state():
    assert state.carried_dismissals(None) == []


def test_carried_dismissals_tolerates_state_without_findings():
    assert state.carried_dismissals({"schema": 1}) == []


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


def test_resolve_finds_a_multi_line_snippet():
    # run.py stores several lines of context, and normalize_snippet()
    # collapses newlines - so the search has to slide a multi-line window,
    # not compare one line at a time.
    entry = {"line": 2, "snippet": "def foo():\n    return 1"}
    new_content = "header\ndef foo():\n    return 1\nfooter"
    status, new_line = state.resolve(entry, new_content)
    assert status == "open"


def test_resolve_finds_a_multi_line_snippet_after_it_shifts():
    entry = {"line": 2, "snippet": "def foo():\n    return 1"}
    new_content = "\n".join(["pad"] * 12 + ["def foo():", "    return 1"])
    status, _ = state.resolve(entry, new_content)
    assert status == "open"


def test_resolve_keeps_a_snippetless_finding_open_rather_than_resolving_it():
    # A file-level finding ("this module has no tests") has line null and
    # so no snippet. "I can't check" is not "the code is gone" - resolving
    # it here silently dropped real findings the moment the file changed.
    entry = {"line": None, "snippet": ""}
    status, new_line = state.resolve(entry, "any content at all")
    assert status == "open"
    assert new_line is None


def test_resolve_keeps_a_snippetless_finding_at_its_recorded_line():
    entry = {"line": 7}  # no snippet key at all
    status, new_line = state.resolve(entry, "any content")
    assert status == "open"
    assert new_line == 7


def test_resolve_handles_empty_new_content():
    entry = {"line": 3, "snippet": "def foo(): return 1"}
    status, new_line = state.resolve(entry, "")
    assert status == "resolved"
    assert new_line is None


def test_resolve_handles_a_snippet_longer_than_the_file():
    entry = {"line": 1, "snippet": "a\nb\nc\nd\ne\nf"}
    status, _ = state.resolve(entry, "a\nb")
    assert status == "resolved"


def test_resolve_ignores_comment_only_changes():
    # normalize_snippet strips comments, so adding one above the finding
    # must not make it look resolved.
    entry = {"line": 2, "snippet": "def foo():\n    return 1"}
    new_content = "header\ndef foo():  # newly commented\n    return 1  # here too"
    status, _ = state.resolve(entry, new_content)
    assert status == "open"


def test_resolve_finds_snippet_outside_the_near_window_by_whole_file_search():
    # Moved much further than the +/-30 line window: the near search fails
    # and the whole-file fallback has to catch it.
    entry = {"line": 1, "snippet": "def foo(): return 1"}
    new_content = "\n".join(["pad"] * 200 + ["def foo(): return 1"])
    status, new_line = state.resolve(entry, new_content)
    assert status == "open"
    assert new_line == 201


def test_resolve_does_not_mutate_the_entry():
    entry = {"line": 3, "snippet": "def foo(): return 1"}
    state.resolve(entry, "def foo(): return 1")
    assert entry["line"] == 3


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
