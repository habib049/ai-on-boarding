"""Self-check for gate.py: severity-gated blocking (a cited MINOR is a
non-blocking nit, only CRITICAL/MAJOR block), the three-section verdict
(1.6) - an uncited/rejected CRITICAL or MAJOR, and any unverified finding,
render under "worth a look" rather than being buried in the nits section -
and the invariant-4 severity floor (2.1): a finding whose final severity
ranks below what verify.py recorded as Layer 2's own severity is a hard
failure, never a silent pass-through.
"""
from __future__ import annotations

import gate


def _finding(severity, citation="some-requirement", unverified=False):
    f = {"file": "a.py", "line": 1, "severity": severity, "summary": "x", "citation": citation}
    if unverified:
        f["unverified"] = True
    return f


def test_cited_minor_does_not_block_and_is_a_nit():
    report, ready = gate.render({"findings": [_finding("MINOR")]})
    assert ready is True
    assert "Ready to merge: yes" in report
    assert "## Nits" in report
    assert "## Blocking" not in report
    assert "worth a look" not in report


def test_cited_major_and_critical_block():
    for severity in ("MAJOR", "CRITICAL"):
        report, ready = gate.render({"findings": [_finding(severity)]})
        assert ready is False
        assert "Ready to merge: no" in report
        assert "## Blocking" in report


def test_uncited_critical_does_not_block_but_is_worth_a_look():
    report, ready = gate.render({"findings": [_finding("CRITICAL", citation=None)]})
    assert ready is True
    assert "## Blocking" not in report
    assert "## Unblocked but worth a look" in report
    assert "## Nits" not in report


def test_unverified_finding_is_worth_a_look_even_when_minor():
    report, ready = gate.render({"findings": [_finding("MINOR", unverified=True)]})
    assert ready is True
    assert "## Unblocked but worth a look" in report
    assert "[unverified]" in report


def test_unverified_footer_counts_unverified_findings():
    report, _ = gate.render({"findings": [_finding("MAJOR", citation=None, unverified=True)]})
    assert "Verification unavailable for 1 finding(s)" in report


def test_suppressed_count_footer():
    report, _ = gate.render({"findings": [], "suppressed_count": 4})
    assert "4 additional finding(s) suppressed" in report


def test_severity_floor_holds_when_absent_defaults_to_own_severity():
    # A finding with no l2_severity key at all (e.g. built directly in a
    # test, not through verify.py) must not trip the assertion - it has
    # nothing to have been downgraded from.
    report, ready = gate.render({"findings": [_finding("MAJOR")]})
    assert ready is False


def test_severity_floor_allows_escalation():
    f = _finding("CRITICAL")
    f["l2_severity"] = "MAJOR"
    report, ready = gate.render({"findings": [f]})
    assert ready is False


def test_severity_floor_rejects_downgrade():
    f = _finding("MINOR")
    f["l2_severity"] = "CRITICAL"
    try:
        gate.render({"findings": [f]})
    except AssertionError:
        pass
    else:
        raise AssertionError("expected gate.render to reject a downgraded severity")


def test_nit_with_fingerprint_renders_as_dismissable_checkbox():
    f = _finding("MINOR")
    f["fp"] = "a1b2c3d4e5f6a1b2"
    report, _ = gate.render({"findings": [f]})
    assert "- [ ] `a1b2c3d4`" in report
    assert "Tick a box to dismiss" in report


def test_nit_without_fingerprint_renders_as_plain_bullet():
    report, _ = gate.render({"findings": [_finding("MINOR")]})
    assert "- [ ]" not in report
    assert "Tick a box to dismiss" not in report


def test_dismissed_finding_is_excluded_from_blocking_and_shown_collapsed():
    f = _finding("CRITICAL")
    f["fp"] = "a1b2c3d4e5f6a1b2"
    f["status"] = "dismissed"
    report, ready = gate.render({"findings": [f]})
    assert ready is True  # dismissed, even a CRITICAL, never blocks
    assert "## Blocking" not in report
    assert "Previously dismissed (1)" in report
    assert "- [x] `a1b2c3d4`" in report


def test_resolved_finding_is_excluded_and_shown_collapsed():
    f = _finding("MAJOR")
    f["fp"] = "a1b2c3d4e5f6a1b2"
    f["status"] = "resolved"
    report, ready = gate.render({"findings": [f]})
    assert ready is True
    assert "## Blocking" not in report
    assert "Resolved (1)" in report
    assert "code no longer found" in report


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
