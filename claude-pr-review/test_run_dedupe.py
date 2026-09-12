"""Tests for run.dedupe_findings(): collapsing entries that describe the
same finding, arriving from different sources on the same push. Pure - no
network, no API key.

The case that motivated this: Layer 2 reviews the whole diff fresh every
push and `already_raised_on_this_pr` is only advisory, so it can re-raise
something a carried entry already covers. A live test produced exactly that
- one fingerprint, two entries, two different statuses, rendered in two
sections at once.
"""
from __future__ import annotations

import run

FP = "a1b2c3d4e5f6a1b2"
OTHER_FP = "ffff0000ffff0000"


def _f(fp=FP, status="open", severity="MAJOR", summary="s", **extra):
    return {"fp": fp, "status": status, "severity": severity, "summary": summary,
            "file": "a.py", "line": 1, "citation": "x", **extra}


def test_fresh_and_carried_same_fingerprint_collapse_to_one():
    carried = [_f(summary="carried wording")]
    fresh = [_f(summary="fresh wording")]
    out = run.dedupe_findings(carried, fresh)
    assert len(out) == 1


def test_fresh_content_wins_over_carried():
    carried = [_f(summary="carried wording", severity="MINOR")]
    fresh = [_f(summary="fresh wording", severity="MAJOR")]
    [out] = run.dedupe_findings(carried, fresh)
    assert out["summary"] == "fresh wording"
    assert out["severity"] == "MAJOR"


def test_dismissed_survives_a_fresh_reraise():
    # The whole point of dismissal: Layer 2 raising it again must not undo
    # a human's decision.
    dismissed = [_f(status="dismissed")]
    fresh = [_f(status="open")]
    [out] = run.dedupe_findings(dismissed, fresh)
    assert out["status"] == "dismissed"


def test_dismissed_survives_regardless_of_group_order():
    fresh = [_f(status="open")]
    dismissed = [_f(status="dismissed")]
    [out] = run.dedupe_findings(fresh, dismissed)
    assert out["status"] == "dismissed"


def test_live_evidence_overrides_a_stale_resolved():
    # If re-anchoring said "code is gone" but this push's Layer 2 found the
    # same thing again, the finding is plainly not resolved.
    resolved = [_f(status="resolved")]
    fresh = [_f(status="open")]
    [out] = run.dedupe_findings(resolved, fresh)
    assert out["status"] == "open"


def test_resolved_alone_stays_resolved():
    [out] = run.dedupe_findings([_f(status="resolved")], [])
    assert out["status"] == "resolved"


def test_duplicates_within_a_single_group_collapse():
    # Layer 2 can raise two findings at the same file/line with the same
    # citation - identical fingerprint, same run, no carried entry involved.
    out = run.dedupe_findings([_f(summary="first"), _f(summary="second")])
    assert len(out) == 1
    assert out[0]["summary"] == "second"


def test_different_fingerprints_are_never_merged():
    out = run.dedupe_findings([_f(fp=FP)], [_f(fp=OTHER_FP)])
    assert len(out) == 2


def _no_fp(**kw):
    f = _f(**kw)
    f.pop("fp")
    return f


def test_entries_without_fingerprints_are_never_grouped_together():
    # Grouping on a missing fp would collapse unrelated findings into one.
    out = run.dedupe_findings([_no_fp(summary="a"), _no_fp(summary="b")])
    assert len(out) == 2


def test_entry_without_fingerprint_passes_through_untouched():
    [out] = run.dedupe_findings([_no_fp(summary="no identity")])
    assert out["summary"] == "no identity"


def test_first_seen_is_preserved_from_the_older_entry():
    carried = [_f(first_seen="olds ha")]
    fresh = [_f()]  # a fresh finding has no first_seen yet
    [out] = run.dedupe_findings(carried, fresh)
    assert out["first_seen"] == "olds ha"


def test_first_seen_not_overwritten_by_a_later_value():
    carried = [_f(first_seen="oldest")]
    fresh = [_f(first_seen="newer")]
    [out] = run.dedupe_findings(carried, fresh)
    assert out["first_seen"] == "oldest"


def test_severity_and_l2_severity_come_from_the_same_entry():
    # Mixing them across sources could produce final < l2, which gate.py
    # asserts against (invariant 4).
    carried = [_f(severity="CRITICAL", l2_severity="CRITICAL")]
    fresh = [_f(severity="MINOR", l2_severity="MINOR")]
    [out] = run.dedupe_findings(carried, fresh)
    assert (out["severity"], out["l2_severity"]) == ("MINOR", "MINOR")


def test_output_order_is_stable_by_first_appearance():
    out = run.dedupe_findings(
        [_f(fp="1111111111111111", summary="first")],
        [_f(fp="2222222222222222", summary="second"), _f(fp="1111111111111111", summary="first again")],
    )
    assert [f["fp"] for f in out] == ["1111111111111111", "2222222222222222"]


def test_empty_input_is_empty_output():
    assert run.dedupe_findings([], [], []) == []


def test_unknown_status_is_treated_as_open_rank():
    # Defensive: a state block hand-edited to an unknown status must not
    # silently outrank a dismissal.
    weird = [_f(status="something-else")]
    dismissed = [_f(status="dismissed")]
    [out] = run.dedupe_findings(weird, dismissed)
    assert out["status"] == "dismissed"


# --- resurfacing: a dismissal covers what was dismissed, not an escalation ---

def test_dismissed_nit_resurfaces_when_reraised_more_severely():
    dismissed = [_f(status="dismissed", severity="MINOR", dismissed_at_severity="MINOR")]
    escalated = [_f(status="open", severity="CRITICAL")]
    [out] = run.dedupe_findings(dismissed, escalated)
    assert out["status"] == "open"
    assert out["resurfaced"] is True


def test_dismissal_holds_at_the_same_severity():
    dismissed = [_f(status="dismissed", severity="MINOR", dismissed_at_severity="MINOR")]
    same = [_f(status="open", severity="MINOR")]
    [out] = run.dedupe_findings(dismissed, same)
    assert out["status"] == "dismissed"
    assert "resurfaced" not in out


def test_dismissal_holds_when_reraised_less_severely():
    dismissed = [_f(status="dismissed", severity="MAJOR", dismissed_at_severity="MAJOR")]
    softer = [_f(status="open", severity="MINOR")]
    [out] = run.dedupe_findings(dismissed, softer)
    assert out["status"] == "dismissed"


def test_ceiling_falls_back_to_the_dismissed_entrys_own_severity():
    # State written before dismissed_at_severity existed still compares
    # correctly - no migration needed.
    dismissed = [_f(status="dismissed", severity="MINOR")]  # no dismissed_at_severity
    escalated = [_f(status="open", severity="MAJOR")]
    [out] = run.dedupe_findings(dismissed, escalated)
    assert out["status"] == "open"
    assert out["resurfaced"] is True


def test_ceiling_is_carried_onto_the_merged_entry():
    # The fresh finding never had a ceiling; without carrying it, the tick
    # still sitting in the comment text would re-dismiss the escalation.
    dismissed = [_f(status="dismissed", severity="MINOR", dismissed_at_severity="MINOR")]
    escalated = [_f(status="open", severity="CRITICAL")]
    [out] = run.dedupe_findings(dismissed, escalated)
    assert out["dismissed_at_severity"] == "MINOR"


def test_ceiling_is_carried_even_when_the_dismissal_still_holds():
    dismissed = [_f(status="dismissed", severity="MINOR", dismissed_at_severity="MINOR")]
    same = [_f(status="open", severity="MINOR")]
    [out] = run.dedupe_findings(dismissed, same)
    assert out["dismissed_at_severity"] == "MINOR"


def test_does_not_mutate_its_inputs():
    carried = [_f(status="dismissed")]
    fresh = [_f(status="open")]
    run.dedupe_findings(carried, fresh)
    assert carried[0]["status"] == "dismissed"
    assert fresh[0]["status"] == "open"


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
