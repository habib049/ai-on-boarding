"""End-to-end lifecycle tests: several pushes on one PR, driven entirely
through the real state/dedupe/render/post code with GitHub and the model
stubbed out. No network, no API key.

This is the offline equivalent of the plan's manual acceptance test ("open
a throwaway PR, push 3 times, confirm one comment, tick a box, push again,
confirm the finding stays dismissed") - the live run that first exposed
these paths cost three CI runs to tell us what these assertions now check
in milliseconds.
"""
from __future__ import annotations

import post
import run
import state


class _FakeGitHub:
    """A stand-in for the one PR comment thread, implementing the same
    interface github.py exposes: read the comments, PATCH one in place, or
    POST a new one.

    Before the GitHub surface was consolidated into one module this had to
    fake `subprocess.run` and parse `gh` argv to work out whether a call was
    a PATCH or a POST - brittle, and it silently missed the second copy of
    the helper that lived in run.py.
    """

    def __init__(self):
        self.comments: list[dict] = []
        self.post_count = 0
        self.patch_count = 0

    def pr_comments(self, repo, pr):
        return self.comments

    def update_comment(self, repo, comment_id, body):
        for c in self.comments:
            if c["id"] == comment_id:
                c["body"] = body
        self.patch_count += 1

    def create_comment(self, pr, body):
        self.comments.append({"id": 100 + len(self.comments),
                              "body": body, "user": {"type": "Bot"}})
        self.post_count += 1

    def tick(self, short_id: str):
        """Simulate a human ticking a dismissal checkbox in the UI."""
        self.comments[-1]["body"] = self.comments[-1]["body"].replace(
            f"- [ ] `{short_id}`", f"- [x] `{short_id}`", 1
        )

    @property
    def body(self) -> str:
        return self.comments[-1]["body"]

    @property
    def state(self) -> dict:
        return state.parse(self.body)


def _push(gh: _FakeGitHub, findings: list[dict], head: str = "sha", files=None):
    """One push: whatever findings this run produced, through post.post()."""
    original = post.github
    post.github = gh
    try:
        return post.post("o/r", "1", findings,
                         {"schema": 1, "head": head, "files": files or {}})
    finally:
        post.github = original


def _finding(fp="a1b2c3d4e5f6a1b2", status="open", severity="MINOR", citation="ruff:F401",
             summary="unused import", file="a.py", line=1):
    return {"fp": fp, "status": status, "severity": severity, "citation": citation,
            "summary": summary, "file": file, "line": line, "snippet": "import os"}


def test_three_pushes_leave_exactly_one_comment():
    gh = _FakeGitHub()
    for i in range(3):
        _push(gh, [_finding()], head=f"sha{i}")
    assert len(gh.comments) == 1
    assert gh.post_count == 1
    assert gh.patch_count == 2


def test_state_round_trips_across_pushes():
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1", files={"a.py": "blob1"})
    first = gh.state
    assert first["head"] == "sha1"

    # The next push reads the prior state back out, exactly as run.py does.
    prior = state.parse(gh.body)
    carried, unchanged = state.carry_forward(prior, {"a.py": "blob1"})
    assert unchanged == {"a.py"}
    assert len(carried) == 1


def test_tick_then_push_keeps_the_finding_dismissed():
    # The plan's headline acceptance criterion.
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    assert "- [ ] `a1b2c3d4`" in gh.body

    gh.tick("a1b2c3d4")
    result = _push(gh, [_finding()], head="sha2")

    assert [f["status"] for f in gh.state["findings"]] == ["dismissed"]
    assert "Previously dismissed" in gh.body
    assert result["ready"] is True


def test_rendered_verdict_always_matches_the_stored_state():
    # The ordering bug the live test caught: the tick landed in the stored
    # state while that same push's own verdict still called it blocking.
    # Whatever the outcome, the text and the state must agree.
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    gh.tick("a1b2c3d4")
    result = _push(gh, [_finding()], head="sha2")

    stored_statuses = [f["status"] for f in gh.state["findings"]]
    assert stored_statuses == ["dismissed"]
    # ...and the text posted in the same write agrees with that.
    assert "Previously dismissed" in gh.body
    assert "## Blocking" not in result["report"]
    assert result["ready"] is True


def test_dismissed_nit_resurfaces_when_later_judged_more_severe():
    # A human waived a MINOR. A later push judges the same code CRITICAL.
    # The dismissal covers what was dismissed, not an escalation of it -
    # otherwise ticking a nit silently suppresses a security finding.
    gh = _FakeGitHub()
    _push(gh, [_finding(severity="MINOR")], head="sha1")
    gh.tick("a1b2c3d4")
    _push(gh, [_finding(severity="MINOR")], head="sha2")

    carried = state.carried_dismissals(gh.state)
    assert carried[0]["dismissed_at_severity"] == "MINOR"

    escalated = _finding(severity="CRITICAL", citation="a real convention",
                         summary="this is actually a credential leak")
    result = _push(gh, run.dedupe_findings(carried, [escalated]), head="sha3")

    assert result["ready"] is False
    assert "## Blocking" in result["report"]
    assert "resurfaced" in result["report"]


def test_dismissal_holds_when_severity_does_not_escalate():
    gh = _FakeGitHub()
    _push(gh, [_finding(severity="MINOR")], head="sha1")
    gh.tick("a1b2c3d4")
    _push(gh, [_finding(severity="MINOR")], head="sha2")

    carried = state.carried_dismissals(gh.state)
    result = _push(gh, run.dedupe_findings(carried, [_finding(severity="MINOR")]), head="sha3")

    assert [f["status"] for f in gh.state["findings"]] == ["dismissed"]
    assert result["ready"] is True


def test_dismissal_survives_a_push_that_does_not_reraise_it():
    # Durability: the dismissal lives in state, not only in the rendered
    # checkbox line. A push where Layer 2 stays quiet must not lose it.
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    gh.tick("a1b2c3d4")
    _push(gh, [_finding()], head="sha2")

    dismissed = state.carried_dismissals(gh.state)
    assert len(dismissed) == 1

    # Push 3 finds nothing new; the dismissal is carried forward explicitly.
    _push(gh, run.dedupe_findings(dismissed, []), head="sha3")
    assert [f["status"] for f in gh.state["findings"]] == ["dismissed"]

    # Push 4: Layer 2 raises it again. It must stay dismissed.
    carried = state.carried_dismissals(gh.state)
    result = _push(gh, run.dedupe_findings(carried, [_finding(status="open")]), head="sha4")
    assert [f["status"] for f in gh.state["findings"]] == ["dismissed"]
    assert result["ready"] is True


def test_untick_then_push_raises_the_finding_again():
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    gh.tick("a1b2c3d4")
    _push(gh, [_finding()], head="sha2")
    assert [f["status"] for f in gh.state["findings"]] == ["dismissed"]

    # The reviewer changes their mind and clears the box.
    gh.comments[-1]["body"] = gh.body.replace("- [x] `a1b2c3d4`", "- [ ] `a1b2c3d4`", 1)
    carried = state.carried_dismissals(gh.state)
    _push(gh, run.dedupe_findings(carried, [_finding()]), head="sha3")

    assert [f["status"] for f in gh.state["findings"]] == ["open"]
    assert "- [ ] `a1b2c3d4`" in gh.body     # back in the nits list, tickable again
    assert "Previously dismissed" not in gh.body


def test_a_materially_changed_finding_comes_back_as_new():
    # Dismissal is keyed to the fingerprint. If the code changes enough to
    # change the fingerprint, that is a genuinely different finding and
    # should be raised again - the dismissal must NOT suppress it.
    gh = _FakeGitHub()
    _push(gh, [_finding(fp="1111111111111111")], head="sha1")
    gh.tick("11111111")
    _push(gh, [_finding(fp="1111111111111111")], head="sha2")

    carried = state.carried_dismissals(gh.state)
    reworked = _finding(fp="2222222222222222", summary="different code now")
    _push(gh, run.dedupe_findings(carried, [reworked]), head="sha3")

    statuses = {f["fp"]: f["status"] for f in gh.state["findings"]}
    assert statuses["1111111111111111"] == "dismissed"
    assert statuses["2222222222222222"] == "open"


def test_reraised_finding_is_not_duplicated_in_the_comment():
    # The duplicate the live test surfaced: one fingerprint rendered twice,
    # in two sections, with two statuses.
    gh = _FakeGitHub()
    carried = [_finding(status="open", summary="carried wording")]
    fresh = [_finding(status="open", summary="fresh wording")]
    _push(gh, run.dedupe_findings(carried, fresh), head="sha1")

    assert len(gh.state["findings"]) == 1
    assert gh.body.count("`a1b2c3d4`") == 1
    assert gh.state["findings"][0]["summary"] == "fresh wording"


def test_resolved_then_found_again_is_open_not_resolved():
    gh = _FakeGitHub()
    resolved = [_finding(status="resolved")]
    fresh = [_finding(status="open")]
    _push(gh, run.dedupe_findings(resolved, fresh), head="sha1")
    assert [f["status"] for f in gh.state["findings"]] == ["open"]
    assert "Resolved" not in gh.body


def test_corrupt_state_cold_starts_without_losing_the_run():
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    # Someone mangles the JSON block in the comment.
    gh.comments[-1]["body"] = gh.body.replace('{"schema"', '{"schema"BROKEN')

    assert state.parse(gh.body) is None  # cold start, no exception
    result = _push(gh, [_finding()], head="sha2")
    assert result["ready"] is True
    assert gh.state is not None  # and the state block is healthy again


def test_a_human_quoting_the_verdict_does_not_hijack_the_sticky_comment():
    gh = _FakeGitHub()
    _push(gh, [_finding()], head="sha1")
    bot_comment_id = gh.comments[0]["id"]
    # A reviewer quotes the bot; GitHub copies the raw body, marker and all.
    gh.comments.append({"id": 999, "body": f"> {gh.body}\n\nwhy is this flagged?",
                        "user": {"type": "User"}})

    _push(gh, [_finding()], head="sha2")

    assert gh.comments[0]["id"] == bot_comment_id
    assert state.parse(gh.comments[0]["body"])["head"] == "sha2"   # bot's own updated
    assert "why is this flagged?" in gh.comments[1]["body"]        # human's untouched


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
