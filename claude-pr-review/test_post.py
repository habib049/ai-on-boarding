"""Tests for post.py's pure logic: finding the sticky comment by marker,
and building the posted body. The actual `gh` calls are I/O and are not
exercised here - see post.py's docstring for why the ordering (read
immediately before write) can't be meaningfully unit-tested without a real
PR, and test_state.py already covers apply_dismissals() itself.
"""
from __future__ import annotations

import post
import state


def test_find_existing_comment_returns_id_when_marker_present():
    comments = [
        {"id": 111, "body": "just a normal comment"},
        {"id": 222, "body": f"# PR Review Verdict\n<!-- {state.MARKER}\n{{}}\n-->"},
    ]
    assert post.find_existing_comment_id(comments) == 222


def test_find_existing_comment_returns_none_when_absent():
    comments = [{"id": 111, "body": "just a normal comment"}]
    assert post.find_existing_comment_id(comments) is None


def test_find_existing_comment_empty_list():
    assert post.find_existing_comment_id([]) is None


def test_find_existing_comment_prefers_the_last_marker_match():
    # Quoting a comment on GitHub copies its raw body, HTML comment and
    # all - so a human quoting the verdict creates a second comment
    # carrying the marker. Taking the first match would make the agent
    # start editing that person's comment.
    comments = [
        {"id": 111, "body": f"> quoting the bot\n<!-- {state.MARKER}\n{{}}\n-->"},
        {"id": 222, "body": f"# PR Review Verdict\n<!-- {state.MARKER}\n{{}}\n-->"},
    ]
    assert post.find_existing_comment_id(comments) == 222


def test_find_existing_comment_prefers_a_bot_authored_match():
    comments = [
        {"id": 111, "body": f"<!-- {state.MARKER}\n{{}}\n-->", "user": {"type": "Bot"}},
        {"id": 222, "body": f"> quote\n<!-- {state.MARKER}\n{{}}\n-->", "user": {"type": "User"}},
    ]
    assert post.find_existing_comment_id(comments) == 111


def test_find_existing_comment_takes_last_bot_match_when_several():
    comments = [
        {"id": 111, "body": f"<!-- {state.MARKER}\n{{}}\n-->", "user": {"type": "Bot"}},
        {"id": 222, "body": f"<!-- {state.MARKER}\n{{}}\n-->", "user": {"type": "Bot"}},
    ]
    assert post.find_existing_comment_id(comments) == 222


def test_find_existing_comment_tolerates_a_null_body():
    assert post.find_existing_comment_id([{"id": 1, "body": None}]) is None


def test_find_existing_comment_tolerates_missing_user_field():
    comments = [{"id": 111, "body": f"<!-- {state.MARKER}\n{{}}\n-->"}]
    assert post.find_existing_comment_id(comments) == 111


def test_build_comment_body_embeds_state_marker():
    body = post.build_comment_body("# PR Review Verdict\n\n**Ready to merge: yes**", {"schema": 1, "findings": []})
    assert state.MARKER in body
    assert "Ready to merge: yes" in body
    # And the result must itself be parseable back into the same state -
    # this is the round trip the next run's carry_forward() depends on.
    assert state.parse(body) == {"schema": 1, "findings": []}


def test_post_renders_after_reconciling_the_fresh_tick_not_before():
    # Regression for a real bug a live test caught: post() used to reconcile
    # dismissals into the *stored state* but render the posted text/exit
    # code from a copy computed earlier, so a tick applied on the triggering
    # push showed "dismissed" in state while the same push's own verdict
    # still said blocking. gate.render() must run here, after reconciliation.
    finding = {"file": "a.py", "line": 1, "severity": "MAJOR", "citation": "x",
               "summary": "s", "fp": "a1b2c3d4e5f6a1b2", "status": "open"}

    # A human just ticked a1b2c3d4 on the *actual* live comment - simulate
    # that by making the fetched body contain the ticked checkbox line,
    # which is what apply_dismissals() reads.
    fake_comments = [{
        "id": 999,
        "body": (
            "# PR Review Verdict\n- [x] `a1b2c3d4` MAJOR `a.py:1` - s\n"
            f"<!-- {state.MARKER}\n{{}}\n-->"
        ),
    }]

    written = {}

    class _FakeGitHub:
        def pr_comments(self, repo, pr):
            return fake_comments

        def update_comment(self, repo, comment_id, body):
            written["body"] = body

        def create_comment(self, pr, body):
            written["body"] = body

    original = post.github
    post.github = _FakeGitHub()
    try:
        result = post.post("owner/repo", "1", [finding], {"schema": 1, "head": "sha", "files": {}})
    finally:
        post.github = original

    assert result["ready"] is True  # dismissed, so no longer blocking
    assert "Ready to merge: yes" in result["report"]
    assert "## Blocking" not in result["report"]
    # And the write itself carried the reconciled (dismissed) state, not a
    # stale pre-reconciliation copy.
    written_state = state.parse(written["body"])
    assert written_state["findings"][0]["status"] == "dismissed"


# --- 3.3: GitHub's 65536-char comment cap ---

def _bulky(status, n, chars=3000):
    return [
        {"fp": f"{i:016x}", "status": status, "severity": "MINOR", "file": "a.py",
         "line": 1, "citation": "x", "summary": "y" * chars}
        for i in range(n)
    ]


def test_normal_sized_verdict_is_left_alone():
    new_state = {"schema": 1, "findings": _bulky("open", 2, chars=50)}
    body, report, ready = post.fit_to_comment_limit(new_state)
    assert len(body) <= post.MAX_COMMENT_CHARS
    assert "truncated" not in body


def test_oversized_verdict_drops_resolved_entries_first():
    findings = _bulky("open", 2) + _bulky("resolved", 30)
    body, report, ready = post.fit_to_comment_limit({"schema": 1, "findings": findings})
    assert len(body) <= post.MAX_COMMENT_CHARS
    written = state.parse(body)
    assert all(f["status"] != "resolved" for f in written["findings"])
    # The open findings - the ones a reviewer actually needs - survive.
    assert any(f["status"] == "open" for f in written["findings"])


def test_dismissals_survive_by_trimming_prose_instead_of_dropping_them():
    # Trimming stored summaries comes before dropping dismissed entries:
    # words are cheap to lose, a human's dismissal decision is not.
    findings = _bulky("open", 2) + _bulky("resolved", 20) + _bulky("dismissed", 20)
    body, _, _ = post.fit_to_comment_limit({"schema": 1, "findings": findings})
    assert len(body) <= post.MAX_COMMENT_CHARS
    written = state.parse(body)
    assert sum(1 for f in written["findings"] if f["status"] == "dismissed") == 20
    assert all(f["status"] != "resolved" for f in written["findings"])


def test_dismissed_entries_are_dropped_only_as_a_last_resort():
    # Enough trimmed entries that even the shortened state block overflows.
    findings = _bulky("open", 2, chars=50) + _bulky("dismissed", 400, chars=3000)
    body, _, _ = post.fit_to_comment_limit({"schema": 1, "findings": findings})
    assert len(body) <= post.MAX_COMMENT_CHARS
    written = state.parse(body)
    assert written is not None  # still parseable, whatever else was lost
    assert any(f["status"] == "open" for f in written["findings"])


def test_state_block_stays_parseable_even_under_extreme_load():
    # The last-resort path cuts prose, never the JSON - a half-written
    # state block parses as corrupt next run, which would throw away every
    # dismissal along with it.
    findings = _bulky("open", 400, chars=3000)
    body, _, _ = post.fit_to_comment_limit({"schema": 1, "head": "abc", "findings": findings})
    assert len(body) <= post.MAX_COMMENT_CHARS
    written = state.parse(body)
    assert written is not None
    assert written["head"] == "abc"


def test_truncation_is_announced_in_the_body():
    findings = _bulky("open", 400, chars=3000)
    body, _, _ = post.fit_to_comment_limit({"schema": 1, "findings": findings})
    assert "truncated" in body.lower()


def test_extreme_shedding_keeps_the_most_severe_findings():
    # When even trimmed entries overflow, what survives should be what a
    # reviewer most needs - not whichever happened to be first in the list.
    minors = [{"fp": f"{i:016x}", "status": "open", "severity": "MINOR", "file": "a.py",
               "line": 1, "citation": "x", "summary": "m" * 3000} for i in range(400)]
    critical = {"fp": "c" * 16, "status": "open", "severity": "CRITICAL", "file": "boom.py",
                "line": 1, "citation": "real", "summary": "the one that matters"}
    body, _, _ = post.fit_to_comment_limit({"schema": 1, "findings": minors + [critical]})
    assert len(body) <= post.MAX_COMMENT_CHARS
    written = state.parse(body)
    assert any(f["severity"] == "CRITICAL" for f in written["findings"])


def test_degradation_never_changes_the_verdict():
    # Dropping resolved/dismissed entries must not flip ready - they are
    # excluded from the blocking computation anyway.
    blocking = [{"fp": "f" * 16, "status": "open", "severity": "MAJOR", "file": "a.py",
                 "line": 1, "citation": "real", "summary": "z" * 100}]
    findings = blocking + _bulky("resolved", 30)
    _, _, ready = post.fit_to_comment_limit({"schema": 1, "findings": findings})
    assert ready is False


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
