"""Single CI entrypoint for a PR push (Phase 3: memory across pushes).
Replaces the workflow's three separate judge.py/verify.py/gate.py steps
with one script so state can flow between them:

  1. Read the sticky comment (if any) -> prior_state. Corrupt/missing state
     always cold-starts (state.parse never raises).
  2. Diff prior_state.files against this push's file blob SHAs:
     - unchanged files -> their prior open findings carry forward as-is,
       Layer 3 skipped entirely for them (state.carry_forward).
     - changed files -> each prior open finding there is re-anchored by
       snippet search (state.resolve): found nearby -> still carried,
       open, Layer 3 skipped; not found -> marked resolved, code is gone.
     - files no longer in the diff (deleted/renamed away) -> resolved.
  3. judge.judge(..., carried=carried) - Layer 2 sees carried findings as
     "already raised, do not repeat" but still reviews the WHOLE diff (not
     restricted to changed files - see judge.py's docstring for why).
  4. verify.verify() on judge's NEW findings only - carried/resolved
     findings never re-enter Layer 3.
  5. Every new finding gets a fingerprint (fingerprint.fingerprint) so a
     future push can recognize and carry it forward in turn.
  6. gate.render() on carried + new + resolved findings together.
  7. post.post() - re-fetches the comment fresh, reconciles any dismissal
     tick made since this job started, PATCHes/POSTs.

Files/snippets for re-anchoring are read via target.REPO_ROOT (the local
checkout), not fetched from GitHub - CI already has the PR's head checked
out.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import anthropic
import fingerprint
import gate
import judge
import post
import state
import target
import verify

REPO_ROOT = target.REPO_ROOT
SNIPPET_CONTEXT_LINES = 2


def _gh_json(*args: str):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise post.PostError(f"gh {' '.join(args)} failed: {result.stderr}")
    return json.loads(result.stdout)


def fetch_prior_state(repo: str, pr: str) -> dict | None:
    comments = _gh_json("api", f"repos/{repo}/issues/{pr}/comments")
    comment_id = post.find_existing_comment_id(comments)
    if comment_id is None:
        return None
    body = next(c["body"] for c in comments if c["id"] == comment_id)
    return state.parse(body)


def fetch_current_blobs(repo: str, pr: str) -> dict[str, str]:
    files = _gh_json("api", f"repos/{repo}/pulls/{pr}/files", "--paginate")
    return {f["filename"]: f["sha"] for f in files if "sha" in f}


def _read_file(path: str) -> str | None:
    full = REPO_ROOT / path
    if not full.is_file():
        return None
    return full.read_text(errors="replace")


def _snippet_for(file: str, line: int | None) -> str:
    if line is None:
        return ""
    content = _read_file(file)
    if content is None:
        return ""
    lines = content.splitlines()
    start = max(0, line - 1 - SNIPPET_CONTEXT_LINES)
    end = min(len(lines), line + SNIPPET_CONTEXT_LINES)
    return "\n".join(lines[start:end])


def reanchor_changed_files(prior_state: dict | None, unchanged: set[str]) -> tuple[list[dict], list[dict]]:
    """For every prior open finding NOT covered by the fast unchanged-file
    path, try to re-find its snippet in the current file content. Returns
    (re_anchored_open, resolved).
    """
    if not prior_state:
        return [], []
    open_elsewhere = [
        f for f in prior_state.get("findings", [])
        if f.get("status") == "open" and f.get("file") not in unchanged
    ]
    re_anchored, resolved = [], []
    for f in open_elsewhere:
        content = _read_file(f["file"])
        if content is None:
            resolved.append({**f, "status": "resolved"})
            continue
        status, new_line = state.resolve(f, content)
        if status == "open":
            re_anchored.append({**f, "line": new_line, "status": "open"})
        else:
            resolved.append({**f, "status": "resolved"})
    return re_anchored, resolved


def attach_metadata(findings: list[dict]) -> list[dict]:
    """Stamp every fresh finding with a fingerprint and the snippet it was
    computed from. state.resolve() re-anchors a carried finding by
    searching a future push's changed file content for this exact snippet
    - a finding missing it always looks resolved (empty target), whether
    or not the code is actually still there.
    """
    out = []
    for f in findings:
        f = dict(f)
        snippet = _snippet_for(f.get("file"), f.get("line"))
        f["fp"] = fingerprint.fingerprint(f, snippet)
        f["snippet"] = snippet
        f.setdefault("status", "open")
        out.append(f)
    return out


def run(client, repo: str, pr: str, head_sha: str) -> dict:
    prior_state = fetch_prior_state(repo, pr)
    current_blobs = fetch_current_blobs(repo, pr)

    carried, unchanged = state.carry_forward(prior_state, current_blobs)
    re_anchored, resolved = reanchor_changed_files(prior_state, unchanged)
    all_carried = carried + re_anchored

    judge_result = judge.judge(client, pr, carried=all_carried)
    new_findings = judge_result.get("findings", [])
    verified = verify.verify(
        client, target.get_diff(pr), target.repo_rules(), {"findings": new_findings}
    )

    new_with_metadata = attach_metadata(verified.get("findings", []))
    for f in all_carried:
        f.setdefault("status", "open")

    combined = all_carried + new_with_metadata + resolved
    combined_result = {"findings": combined, "suppressed_count": judge_result.get("suppressed_count", 0)}
    report, ready = gate.render(combined_result)

    base_state = {"schema": 1, "head": head_sha, "files": current_blobs}
    post.post(repo, pr, report, combined, base_state)

    return {"report": report, "ready": ready}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()

    client = anthropic.Anthropic()
    result = run(client, args.repo, args.pr, args.head_sha)
    print(result["report"])
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
