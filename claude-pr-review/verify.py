"""Layer 3: independently re-check Layer 2's findings before any of them can
block a merge - confirms each citation is real and each failure scenario
actually holds. Verification and classification are different jobs: Layer 3
can only confirm/reject a citation and upgrade a severity, never assign or
lower one - see agent.VERIFICATION_SCHEMA and _apply_verification().

Two of the three citation forms (a ruff code, a quoted convention string, a
named test) are mechanically checkable - citations.precheck() does that in
code, deterministically, for free. Only a citation precheck can't resolve
(NEEDS_MODEL) spends a real agent.run() call. On a typical PR that cuts
Layer 3's call volume by roughly a third.

The model is never told Layer 2's severity - a verifier told "this is
CRITICAL" tends to find reasons it's critical; asked to independently assess
and only optionally escalate, it doesn't inherit the bias. CRITICAL-severity
findings route to Sonnet rather than Haiku (MODEL_FOR_SEVERITY): getting a
CRITICAL verdict wrong is the expensive direction to be wrong in, and the
citation precheck's cut to call volume is what makes that affordable.

Verifies one finding per agent.run() call, not the whole batch in one call.
A live test (PR #7, run 34456550640) showed the batched version had no way
to stop one hard finding from consuming the entire tool-use budget and
starving the rest - splitting per-finding bounds that structurally: a stuck
or wrong verification on one finding can't affect any other, each gets its
own fresh MAX_ITERATIONS budget.

Fails closed: a call that keeps erroring after MAX_RETRIES attempts is not
evidence against the finding, so severity and citation are preserved as-is
(marked `unverified: true` for a human to see) rather than stripping the
citation and letting infrastructure flake unblock a merge.

The diff+rules content is identical across every call for one PR, so
it's passed as agent.run()'s cached stable_content and only the one
finding being checked varies per call - see agent.py's cache_control
handling for why that keeps the repeated-call cost down.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import agent
import anthropic
import citations
import severity
import target
import tools

MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-5"
# Haiku doesn't support the task_budget beta (agent.py's TASK_BUDGET_BETA),
# so only the Sonnet route gets one; Haiku relies on MAX_ITERATIONS alone,
# same as before this table existed - now explicit per route rather than
# uniform across all of Layer 3.
MODEL_FOR_SEVERITY = {"CRITICAL": MODEL_SONNET, "MAJOR": MODEL_HAIKU, "MINOR": MODEL_HAIKU}
SONNET_TASK_BUDGET = agent.MIN_TASK_BUDGET_TOKENS

MAX_RETRIES = 3
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "verify.md").read_text()

_TEST_DEF_RE = re.compile(r"^\s*def (test_[A-Za-z0-9_]+)", re.M)


class _Context:
    """citations.precheck()'s ctx. Built once per verify() call, not per
    finding - test_index is a whole-repo scan.
    """

    def __init__(self, convention_text: str, test_index: set[str]):
        self.convention_text = convention_text
        self.test_index = test_index

    def lint_codes_near(self, file: str, line: int | None, window: int = 3) -> set[str]:
        # Layer 3 doesn't retain Layer 1's raw per-location ruff codes (only
        # judge.py sees them, before folding into findings). A lint-sourced
        # finding is already CONFIRMED via precheck's source == "lint"
        # branch regardless of this method, so this only matters for a
        # judge-model finding independently claiming a "ruff:<code>"
        # citation it wasn't given by Layer 1 - rare, and safer to reject
        # deterministically than to risk a false confirm with no real data.
        return set()


def _build_test_index() -> set[str]:
    names: set[str] = set()
    for root, dirnames, filenames in os.walk(target.REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in tools.SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            try:
                content = (Path(root) / name).read_text(errors="replace")
            except OSError:
                continue
            names.update(_TEST_DEF_RE.findall(content))
    return names


def build_stable_content(diff: str, rules: dict) -> str:
    return json.dumps({"diff": agent.wrap_untrusted(diff), "rules": rules})


def _redact_for_model(finding: dict) -> str:
    # Don't prime the verifier with Layer 2's severity label - it should
    # reach its own judgment on how bad this is, then only ever escalate.
    redacted = {k: v for k, v in finding.items() if k not in ("severity", "l2_severity")}
    return json.dumps({"finding": redacted})


def _apply_verification(finding: dict, verdict: dict) -> list[dict]:
    if not verdict.get("verified", False):
        return []  # the claimed failure scenario doesn't actually hold

    out = dict(finding)
    if not verdict.get("citation_holds", False):
        out["citation"] = None
    escalate_to = verdict.get("escalate_to")
    if escalate_to:
        out["severity"] = severity.max_severity(out["severity"], escalate_to)
    out["verified"] = True
    return [out]


def _verify_one(client, stable_content: str, finding: dict) -> list[dict]:
    model = MODEL_FOR_SEVERITY.get(finding.get("l2_severity"), MODEL_HAIKU)
    task_budget = SONNET_TASK_BUDGET if model == MODEL_SONNET else None
    variable_content = _redact_for_model(finding)

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            verdict = agent.run(
                client, model, SYSTEM_PROMPT, stable_content, variable_content,
                output_schema=agent.VERIFICATION_SCHEMA, task_budget=task_budget,
            )
            return _apply_verification(finding, verdict)
        except (agent.AgentError, anthropic.APIError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

    # Every retry failed. Not evidence against the finding - keep it as-is
    # (severity and citation untouched, never downgraded) so infrastructure
    # flake can't unblock a merge; gate.py's blocking condition is unchanged,
    # so this only blocks if the original finding already would have.
    print(
        f"[verify] verification unavailable after {MAX_RETRIES} attempts, keeping finding as-is: {last_exc}\n"
        f"  {finding.get('file')}:{finding.get('line')} - {finding.get('summary', '')[:120]}",
        file=sys.stderr,
    )
    unverified = dict(finding)
    unverified["unverified"] = True
    unverified["unverified_reason"] = str(last_exc)
    return [unverified]


def verify(client, diff: str, rules: dict, findings: dict) -> dict:
    items = findings.get("findings", [])
    if not items:
        return {"findings": []}

    ctx = _Context(convention_text="\n".join(rules.values()), test_index=_build_test_index())
    stable_content = build_stable_content(diff, rules)
    verified = []
    for original in items:
        # l2_severity is Layer 2's own verdict, carried through every path
        # below unchanged - gate.py asserts final severity never ranks
        # below it (invariant 4: Layer 3 may escalate, never downgrade).
        finding = dict(original)
        finding["l2_severity"] = finding.get("severity")

        if finding.get("source") == "lint":
            # ruff already confirmed this - not a model claim to re-check.
            verified.append(finding)
            continue

        outcome = citations.precheck(finding, ctx)
        if outcome is citations.Precheck.CONFIRMED:
            verified.append(finding)
            continue
        if outcome is citations.Precheck.REJECTED:
            # The citation doesn't check out, but that isn't grounds to drop
            # a real bug - strip the citation (so it can never block) and
            # keep the finding, severity untouched.
            rejected = dict(finding)
            rejected["citation"] = None
            verified.append(rejected)
            continue

        verified.extend(_verify_one(client, stable_content, finding))

    result = {"findings": verified}
    if "suppressed_count" in findings:
        result["suppressed_count"] = findings["suppressed_count"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="PR number, branch, or omit for the working tree")
    parser.add_argument("--findings", type=Path, required=True, help="Path to judge.py's output JSON")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    findings = json.loads(args.findings.read_text())
    client = anthropic.Anthropic()
    diff = target.get_diff(args.target)
    rules = target.repo_rules()
    result = verify(client, diff, rules, findings)

    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
