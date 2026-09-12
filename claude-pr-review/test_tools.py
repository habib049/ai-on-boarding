"""Tests for tools.py's failure signalling and path confinement.

The distinction under test: a tool call that FAILED must come back with
is_error=True, while a call that SUCCEEDED with an empty answer must not.
Conflating them is what let a verifier read "No such file" as a fact about
the repository and drop real findings - the bug the eval fixture staging
was built to work around.
"""
from __future__ import annotations

import tools


def test_reading_a_real_file_succeeds():
    content, is_error = tools.execute("read_file", {"path": "claude-pr-review/severity.py"})
    assert is_error is False
    assert "RANK" in content


def test_missing_file_is_flagged_as_an_error_not_content():
    content, is_error = tools.execute("read_file", {"path": "claude-pr-review/nope.py"})
    assert is_error is True
    assert "No such file" in content


def test_path_escaping_the_repo_is_an_error():
    content, is_error = tools.execute("read_file", {"path": "../../../../etc/passwd"})
    assert is_error is True
    assert "outside the repository" in content


def test_absolute_path_outside_the_repo_is_an_error():
    content, is_error = tools.execute("read_file", {"path": "/etc/passwd"})
    assert is_error is True


def test_unknown_tool_is_an_error():
    content, is_error = tools.execute("rm_rf", {"path": "/"})
    assert is_error is True
    assert "Unknown tool" in content


def test_grep_with_no_matches_is_a_result_not_an_error():
    # The search ran; the answer is empty. Flagging this as an error would
    # tell the model its tool is broken when it just found nothing - and
    # "nothing references this" is often the answer a finding turns on.
    # The pattern is assembled at runtime so this file doesn't contain the
    # literal it searches for and match itself.
    absent = "zzz" + "_definitely_not_in_this_repo_" + "zzz"
    content, is_error = tools.execute("grep", {"pattern": absent, "path": "claude-pr-review"})
    assert is_error is False
    assert content == "No matches."


def test_grep_finds_a_real_symbol():
    content, is_error = tools.execute("grep", {"pattern": "BLOCKING_SEVERITIES", "path": "claude-pr-review"})
    assert is_error is False
    assert "gate.py" in content


def test_grep_pattern_starting_with_a_dash_is_not_parsed_as_a_flag():
    # Without the `--` terminator this reaches rg as an option and the
    # search breaks instead of returning nothing.
    flag_like = "--" + "hiddenzzz_not_a_real_flag"
    content, is_error = tools.execute("grep", {"pattern": flag_like, "path": "claude-pr-review"})
    assert is_error is False
    assert content == "No matches."


def test_list_files_on_a_missing_directory_is_an_error():
    content, is_error = tools.execute("list_files", {"directory": "claude-pr-review/nope"})
    assert is_error is True
    assert "No such directory" in content


def test_list_files_with_no_matches_is_a_result_not_an_error():
    content, is_error = tools.execute(
        "list_files", {"directory": "claude-pr-review", "pattern": "*.nosuchext"}
    )
    assert is_error is False
    assert content == "No files matched."


def test_list_files_skips_heavy_directories():
    content, is_error = tools.execute("list_files", {"directory": "claude-pr-review", "pattern": "*.py"})
    assert is_error is False
    assert ".venv" not in content


def test_every_tool_declares_strict_and_a_closed_schema():
    # strict: true is what guarantees tool_use.input validates against the
    # schema, which is why execute()'s TypeError branch is a backstop rather
    # than a routine path.
    for tool in tools.TOOLS:
        assert tool["strict"] is True, tool["name"]
        assert tool["input_schema"]["additionalProperties"] is False, tool["name"]
        assert "required" in tool["input_schema"], tool["name"]


def test_dispatch_and_tools_declare_the_same_three_tools():
    assert {t["name"] for t in tools.TOOLS} == set(tools.DISPATCH)


def test_no_write_capable_tool_is_exposed():
    # CLAUDE.md invariant 1: exactly three read-only tools, no write, no
    # shell. This is the structural guarantee, so assert it structurally.
    assert set(tools.DISPATCH) == {"read_file", "grep", "list_files"}


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
