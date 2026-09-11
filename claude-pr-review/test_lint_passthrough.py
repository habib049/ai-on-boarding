"""Self-check for the fix: lint findings must reach the final verdict instead
of being discarded after judge.py's dedup filter. Run directly: no API key,
no network - verify() never calls agent.run for lint-sourced findings.
"""
from __future__ import annotations

import judge
import verify


def test_lint_findings_survive_judge_and_verify():
    lint_result = {
        "status": "fail",
        "findings": [{"file": "a.py", "line": 3, "code": "E501", "message": "line too long"}],
    }

    lint_findings = judge._lint_as_findings(lint_result)
    assert lint_findings == [
        {
            "file": "a.py",
            "line": 3,
            "severity": "MINOR",  # E501 -> MINOR under severity.py's ruff map
            "summary": "line too long",
            "citation": "ruff:E501",
            "source": "lint",
        }
    ]

    def _unreachable_client(*_a, **_k):
        raise AssertionError("verify() must not call the agent for lint-sourced findings")

    result = verify.verify(_unreachable_client, diff="", rules={}, findings={"findings": lint_findings})
    [out] = result["findings"]
    assert out["citation"] == "ruff:E501"
    assert out["severity"] == "MINOR"
    assert out["source"] == "lint"


if __name__ == "__main__":
    test_lint_findings_survive_judge_and_verify()
    print("ok")
