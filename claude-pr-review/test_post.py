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


def test_build_comment_body_embeds_state_marker():
    body = post.build_comment_body("# PR Review Verdict\n\n**Ready to merge: yes**", {"schema": 1, "findings": []})
    assert state.MARKER in body
    assert "Ready to merge: yes" in body
    # And the result must itself be parseable back into the same state -
    # this is the round trip the next run's carry_forward() depends on.
    assert state.parse(body) == {"schema": 1, "findings": []}


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
