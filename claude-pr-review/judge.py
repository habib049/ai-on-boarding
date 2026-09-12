"""Layer 2: judge a PR diff for architectural fit, convention compliance,
correctness, and blast radius. Runs Layer 1 (lint.py) first, merges any
model finding landing near a lint finding's (file, line) into that lint
finding rather than dropping it (a straight drop loses the better prose and
misses near-misses where the model flags the usage site instead of the
definition), and folds lint's own findings into the output so they reach
Layer 4's verdict. Caps total findings so uncapped output doesn't multiply
into Layer 3 cost and comment spam.

`carried` (Phase 3, memory across pushes) is the summary of every open
finding a prior run on this same PR already raised on unchanged files. It
is never used to restrict the diff Layer 2 sees - L2 is a single Sonnet
call and its blast-radius analysis depends on seeing the whole change, and
restricting it would save little (see docs/improvement-plan.md, "Phase 3,
3.5" for why the actual cost is in Layer 3, not here). It's passed into the
prompt purely as "already raised, do not repeat" context.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import agent
import anthropic
import lint
import severity
import target

MODEL = "claude-sonnet-5"
TASK_BUDGET_TOKENS = 40_000  # guardrail on total spend for one judge run
MAX_FINDINGS = 15
MERGE_WINDOW = 3
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "judge.md").read_text()


def build_user_content(target_arg: str | None, lint_result: dict, carried: list[dict] | None = None) -> str:
    diff = target.get_diff(target_arg)
    rules = target.repo_rules()
    payload = {"diff": agent.wrap_untrusted(diff), "rules": rules, "layer_1_lint_results": lint_result}
    if carried:
        payload["already_raised_on_this_pr"] = [
            {"file": f.get("file"), "line": f.get("line"), "summary": f.get("summary")}
            for f in carried
        ]
    return json.dumps(payload)


def _lint_as_findings(lint_result: dict) -> list[dict]:
    # ruff already confirmed these - ground truth, not a model claim - so they
    # carry their own citation and skip Layer 3's model-based re-verification
    # (see verify.py's "source" == "lint" passthrough). Severity comes from
    # the rule family, not a blanket MAJOR - an unused import isn't a broken
    # auth path.
    return [
        {
            "file": f["file"],
            "line": f["line"],
            "severity": severity.severity_for_ruff(f["code"]),
            "summary": f["message"],
            "citation": f"ruff:{f['code']}",
            "source": "lint",
        }
        for f in lint_result.get("findings", [])
    ]


def merge_lint_and_model(lint_findings: list[dict], model_findings: list[dict], window: int = MERGE_WINDOW) -> list[dict]:
    out = [dict(f) for f in lint_findings]
    for mf in model_findings:
        hit = next(
            (
                lf for lf in out
                if lf["file"] == mf.get("file")
                and lf.get("line") is not None and mf.get("line") is not None
                and abs(lf["line"] - mf["line"]) <= window
            ),
            None,
        )
        if hit:
            hit["summary"] = mf.get("summary") or hit["summary"]
            hit["severity"] = severity.max_severity(hit["severity"], mf.get("severity", "MINOR"))
        else:
            out.append(mf)
    return out


def _cap_findings(findings: list[dict], limit: int = MAX_FINDINGS) -> tuple[list[dict], int]:
    ranked = sorted(
        findings,
        key=lambda f: (severity.RANK.get(f.get("severity"), 0), bool(f.get("citation"))),
        reverse=True,
    )
    return ranked[:limit], max(0, len(findings) - limit)


def judge(client, target_arg: str | None, carried: list[dict] | None = None) -> dict:
    lint_result = lint.run(target.changed_python_files(target_arg))
    user_content = build_user_content(target_arg, lint_result, carried)

    result = agent.run(client, MODEL, SYSTEM_PROMPT, user_content, task_budget=TASK_BUDGET_TOKENS)

    merged = merge_lint_and_model(_lint_as_findings(lint_result), result.get("findings", []))
    kept, suppressed_count = _cap_findings(merged)

    result["findings"] = kept
    result["suppressed_count"] = suppressed_count
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="PR number, branch, or omit for the working tree")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    client = anthropic.Anthropic()
    result = judge(client, args.target)

    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
