"""Harness-level assertions that don't belong to any one fixture (plan 4.4).

These guard wiring a fixture can't see. The one that matters most: the
review step runs with `continue-on-error: true` so the verdict comment
still gets posted when the answer is "no" - which means a *separate* step
is what actually fails the check. Delete that step and nothing breaks
loudly; the reviewer just quietly becomes advisory and every PR goes green
forever. That is a failure mode worth a standing assertion rather than a
code review someone might not do.

Deliberately string-matched rather than YAML-parsed: pyyaml isn't a
dependency of this tool, and adding one to assert four lines would be a
worse trade than a handful of substring checks.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
REVIEW_WORKFLOW = WORKFLOWS_DIR / "pr-review-agent.yml"
COLLECT_WORKFLOW = WORKFLOWS_DIR / "pr-review-collect.yml"


def _directives(path: Path) -> str:
    """The workflow's actual YAML, with comment lines removed.

    Both files explain *why* they avoid `pull_request_target` and why the
    collect half holds no write permission, so a naive substring search
    finds those strings in prose and reports the opposite of the truth.
    Inline trailing comments count too - `contents: read # never
    pull-requests: write` is a directive that says one thing and a comment
    that mentions another. A check should never pass or fail on prose.
    """
    kept = []
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        directive, _, _ = line.partition(" #")
        kept.append(directive)
    return "\n".join(kept)


def check_gate_exit_path() -> tuple[bool, str]:
    """The review step's failure must still fail the job."""
    if not REVIEW_WORKFLOW.is_file():
        return False, f"{REVIEW_WORKFLOW.name} is missing"
    text = _directives(REVIEW_WORKFLOW)

    if "id: review" not in text:
        return False, "the review step lost its `id: review`, so nothing can key off its outcome"
    if "steps.review.outcome == 'failure'" not in text:
        return False, "no step fails the job on the review step's failure - the reviewer is advisory"
    if "exit 1" not in text:
        return False, "the failure step no longer exits non-zero"
    return True, "a failing review still fails the job"


def check_fork_safety() -> tuple[bool, str]:
    """The untrusted half must stay untrusted, and the trusted half must not
    be reachable from a PR's own code.
    """
    if not COLLECT_WORKFLOW.is_file():
        return False, f"{COLLECT_WORKFLOW.name} is missing - fork PRs would run without secrets"
    collect, review = _directives(COLLECT_WORKFLOW), _directives(REVIEW_WORKFLOW)

    if "pull_request_target" in collect or "pull_request_target" in review:
        return False, "pull_request_target puts secrets in scope on a PR-controlled checkout"
    if "pull-requests: write" in collect:
        return False, "the collect workflow must not hold write permission"
    if "secrets." in collect:
        return False, "the collect workflow must not reference secrets - a fork PR never gets them"
    if "workflow_run" not in review:
        return False, "the review workflow no longer runs in the trusted workflow_run context"
    if "PR_REVIEW_RULES_ROOT" not in review:
        return False, "rules are no longer pinned to the trusted checkout - a PR could rewrite them"
    return True, "the untrusted half holds no secrets and no write access"


CHECKS = {
    "gate_exit_path": check_gate_exit_path,
    "fork_safety": check_fork_safety,
}


def run_all() -> dict[str, dict]:
    results = {}
    for name, check in CHECKS.items():
        ok, message = check()
        results[name] = {"ok": ok, "message": message}
    return results
