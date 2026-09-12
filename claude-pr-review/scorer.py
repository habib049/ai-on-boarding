"""Score one eval case: a produced pipeline result against a fixture's
expected.json. Pure - no I/O, no model calls, no imports from judge.py or
verify.py.

`produced` is {"findings": [...] (verify.py's output shape), "verdict":
"yes"|"no", "cost": {"usd": float} | None}. `expected` is a fixture's
expected.json: {"must_find": [...], "must_not_find": [...],
"expected_verdict": "yes"|"no"}.
"""
from __future__ import annotations

LINE_WINDOW = 3
BLOCKING_SEVERITIES = {"CRITICAL", "MAJOR"}


def _matches(item: dict, finding: dict) -> bool:
    if item.get("file") != finding.get("file"):
        return False
    item_line, finding_line = item.get("line"), finding.get("line")
    if item_line is None or finding_line is None:
        if item_line != finding_line:
            return False
    elif abs(item_line - finding_line) > LINE_WINDOW:
        return False
    category = item.get("category")
    if category and finding.get("category") and finding["category"] != category:
        return False
    return True


def _find_match(item: dict, findings: list[dict]) -> dict | None:
    return next((f for f in findings if _matches(item, f)), None)


def score_case(produced: dict, expected: dict) -> dict:
    findings = produced.get("findings", [])
    must_find = expected.get("must_find", [])
    must_not_find = expected.get("must_not_find", [])

    matched = [item for item in must_find if _find_match(item, findings)]
    recall = len(matched) / len(must_find) if must_find else 1.0

    false_positive_findings = [
        f for item in must_not_find if (f := _find_match(item, findings))
    ]
    if not must_find and not must_not_find:
        # The clean-PR case: nothing is expected at all, so any finding
        # the pipeline raises is itself a false positive.
        false_positive_findings = list(findings)

    verdict_correct = produced.get("verdict") == expected.get("expected_verdict")

    blocking = [f for f in findings if f.get("citation") and f.get("severity") in BLOCKING_SEVERITIES]
    blocking_hits = sum(1 for f in blocking if any(_matches(item, f) for item in must_find))
    blocking_precision = blocking_hits / len(blocking) if blocking else 1.0

    return {
        "recall": recall,
        "false_positives": len(false_positive_findings),
        "verdict_correct": verdict_correct,
        "blocking_precision": blocking_precision,
        "cost_usd": (produced.get("cost") or {}).get("usd"),
    }


def summarize(case_scores: dict[str, dict]) -> dict:
    """Aggregate per-case scores into suite-level numbers."""
    n = len(case_scores)
    if n == 0:
        return {"recall": 1.0, "false_positives": 0, "verdict_accuracy": 1.0, "cost_usd": 0.0}
    return {
        "recall": sum(s["recall"] for s in case_scores.values()) / n,
        "false_positives": sum(s["false_positives"] for s in case_scores.values()),
        "verdict_accuracy": sum(1 for s in case_scores.values() if s["verdict_correct"]) / n,
        "cost_usd": sum(s["cost_usd"] or 0.0 for s in case_scores.values()),
    }
