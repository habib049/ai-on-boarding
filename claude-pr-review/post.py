"""Post the run's verdict as a sticky PR comment - find-and-PATCH the prior
one by state.MARKER rather than POSTing a new comment every push, so ten
pushes leave one comment, not ten.

Ordering matters (3.6): the comment body is re-fetched as the LAST thing
before this job decides what to post, in run(), not at job start where
run.py fetched it to compute carry-forward. If a human ticks a dismissal
checkbox after this job started but before it finishes, a stale copy of
the body (the one run.py used minutes earlier) would silently overwrite
that tick with an un-dismissed version. Re-fetching immediately before the
write and re-running apply_dismissals() against that fresh body is what
prevents that: the only state.parse()/apply_dismissals() pass that decides
what gets written is the one against the comment as it exists right now.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import state


class PostError(RuntimeError):
    pass


def find_existing_comment_id(comments: list[dict]):
    for c in comments:
        if state.MARKER in c.get("body", ""):
            return c["id"]
    return None


def build_comment_body(verdict_report: str, new_state: dict) -> str:
    return verdict_report + "\n" + state.render(new_state)


def _gh_json(*args: str):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise PostError(f"gh {' '.join(args)} failed: {result.stderr}")
    return json.loads(result.stdout)


def post(repo: str, pr: str, verdict_report: str, findings: list[dict], base_state: dict) -> str:
    """Fetch the live comment list (the read this whole ordering exists
    for), reconcile any dismissal ticks against the current body, then
    PATCH the existing sticky comment or POST a new one. Returns the body
    that was written.
    """
    comments = _gh_json("api", f"repos/{repo}/issues/{pr}/comments")
    comment_id = find_existing_comment_id(comments)
    live_body = next((c["body"] for c in comments if c.get("id") == comment_id), "")

    reconciled_findings = state.apply_dismissals(live_body, findings)
    new_state = dict(base_state)
    new_state["findings"] = reconciled_findings
    body = build_comment_body(verdict_report, new_state)

    if comment_id:
        subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/comments/{comment_id}", "-X", "PATCH", "--input", "-"],
            input=json.dumps({"body": body}), text=True, check=True,
        )
    else:
        subprocess.run(["gh", "pr", "comment", pr, "--body", body], check=True)
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True)
    parser.add_argument("--verdict", type=Path, required=True, help="Path to gate.py's rendered verdict.md")
    parser.add_argument("--findings", type=Path, required=True, help="Path to verify.py's output JSON")
    parser.add_argument("--state", type=Path, required=True, help="Path to the state dict (schema/head/files) minus findings")
    args = parser.parse_args()

    verdict_report = args.verdict.read_text()
    findings = json.loads(args.findings.read_text()).get("findings", [])
    base_state = json.loads(args.state.read_text())

    post(args.repo, args.pr, verdict_report, findings, base_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
