"""Test table for scorer.py, written before run_eval.py per the Phase 0
plan. Run directly: pure functions, no API key, no network.
"""
from __future__ import annotations

import scorer


def _finding(file="a.py", line=10, severity="MAJOR", citation="ruff:F401", category=None):
    f = {"file": file, "line": line, "severity": severity, "citation": citation, "summary": "x"}
    if category:
        f["category"] = category
    return f


def test_clean_pr_case_any_finding_is_a_false_positive():
    produced = {"findings": [_finding()], "verdict": "yes"}
    expected = {"must_find": [], "must_not_find": [], "expected_verdict": "yes"}
    result = scorer.score_case(produced, expected)
    assert result["false_positives"] == 1
    assert result["recall"] == 1.0
    assert result["verdict_correct"] is True


def test_clean_pr_case_zero_findings_is_clean():
    produced = {"findings": [], "verdict": "yes"}
    expected = {"must_find": [], "must_not_find": [], "expected_verdict": "yes"}
    result = scorer.score_case(produced, expected)
    assert result["false_positives"] == 0


def test_must_find_matches_within_line_window():
    produced = {"findings": [_finding(line=41)], "verdict": "no"}
    expected = {
        "must_find": [{"file": "a.py", "line": 42, "min_severity": "MAJOR", "should_block": True}],
        "must_not_find": [],
        "expected_verdict": "no",
    }
    result = scorer.score_case(produced, expected)
    assert result["recall"] == 1.0


def test_must_find_misses_outside_line_window():
    produced = {"findings": [_finding(line=50)], "verdict": "no"}
    expected = {
        "must_find": [{"file": "a.py", "line": 42, "min_severity": "MAJOR", "should_block": True}],
        "must_not_find": [],
        "expected_verdict": "no",
    }
    result = scorer.score_case(produced, expected)
    assert result["recall"] == 0.0


def test_must_find_misses_on_wrong_file():
    produced = {"findings": [_finding(file="b.py")], "verdict": "no"}
    expected = {
        "must_find": [{"file": "a.py", "line": 10, "min_severity": "MAJOR", "should_block": True}],
        "must_not_find": [],
        "expected_verdict": "no",
    }
    result = scorer.score_case(produced, expected)
    assert result["recall"] == 0.0


def test_must_not_find_counts_as_false_positive_when_present():
    produced = {"findings": [_finding(file="tests/test_api.py", line=5)], "verdict": "no"}
    expected = {
        "must_find": [],
        "must_not_find": [{"file": "tests/test_api.py", "line": 5, "reason": "bare asserts are a repo convention"}],
        "expected_verdict": "yes",
    }
    result = scorer.score_case(produced, expected)
    assert result["false_positives"] == 1


def test_verdict_mismatch_is_flagged():
    produced = {"findings": [], "verdict": "yes"}
    expected = {"must_find": [], "must_not_find": [], "expected_verdict": "no"}
    result = scorer.score_case(produced, expected)
    assert result["verdict_correct"] is False


def test_blocking_precision_penalizes_unexpected_blocking_finding():
    produced = {
        "findings": [_finding(file="a.py", line=10), _finding(file="c.py", line=1)],
        "verdict": "no",
    }
    expected = {
        "must_find": [{"file": "a.py", "line": 10, "min_severity": "MAJOR", "should_block": True}],
        "must_not_find": [],
        "expected_verdict": "no",
    }
    result = scorer.score_case(produced, expected)
    assert result["blocking_precision"] == 0.5


def test_blocking_precision_ignores_non_blocking_findings():
    produced = {
        "findings": [_finding(file="a.py", line=10), _finding(file="c.py", line=1, citation=None)],
        "verdict": "no",
    }
    expected = {
        "must_find": [{"file": "a.py", "line": 10, "min_severity": "MAJOR", "should_block": True}],
        "must_not_find": [],
        "expected_verdict": "no",
    }
    result = scorer.score_case(produced, expected)
    assert result["blocking_precision"] == 1.0


def test_summarize_aggregates_across_cases():
    scores = {
        "001": {"recall": 1.0, "false_positives": 0, "verdict_correct": True, "blocking_precision": 1.0, "cost_usd": 0.01},
        "002": {"recall": 0.5, "false_positives": 1, "verdict_correct": False, "blocking_precision": 0.0, "cost_usd": 0.02},
    }
    summary = scorer.summarize(scores)
    assert summary["recall"] == 0.75
    assert summary["false_positives"] == 1
    assert summary["verdict_accuracy"] == 0.5
    assert abs(summary["cost_usd"] - 0.03) < 1e-9


def test_summarize_empty_suite_is_vacuously_clean():
    summary = scorer.summarize({})
    assert summary == {"recall": 1.0, "false_positives": 0, "verdict_accuracy": 1.0, "cost_usd": 0.0}


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
