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
  6. post.post(repo, pr, combined, base_state) - re-fetches the comment
     fresh, reconciles any dismissal tick made since this job started,
     THEN renders the verdict from that reconciled list (gate.render()
     lives inside post.post(), not here) and PATCHes/POSTs. One render per
     run, and it reflects the same data that gets written - an earlier
     version rendered before this fetch, so a tick applied on the triggering
     push showed as "dismissed" in the stored state but still blocking in
     that same push's own posted text and exit code.

Files/snippets for re-anchoring are read via target.REPO_ROOT (the local
checkout), not fetched from GitHub - CI already has the PR's head checked
out.
"""
from __future__ import annotations

import argparse
import sys

import anthropic
import fingerprint
import github
import judge
import post
import severity
import state
import target
import verify

REPO_ROOT = target.REPO_ROOT
SNIPPET_CONTEXT_LINES = 2


def fetch_prior_state(repo: str, pr: str) -> dict | None:
    comments = github.pr_comments(repo, pr)
    comment_id = post.find_existing_comment_id(comments)
    if comment_id is None:
        return None
    body = next(c["body"] for c in comments if c["id"] == comment_id)
    return state.parse(body)


def _read_file(path: str) -> str | None:
    full = REPO_ROOT / path
    if not full.is_file():
        return None
    return full.read_text(errors="replace")


def _snippet_for(file: str | None, line: int | None) -> str:
    # A finding can legitimately have no file (a claim about the change as
    # a whole) or no line (a claim about the file as a whole). Neither has
    # a snippet to anchor to; an empty one is correct and state.resolve()
    # knows not to read that as "the code is gone".
    if not file or line is None:
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
        if not f.get("file"):
            # A finding about the change as a whole has no file to re-read
            # and nothing to resolve against - carry it forward untouched
            # rather than inventing a verdict about it.
            re_anchored.append({**f, "status": "open"})
            continue
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


STATUS_RANK = {"resolved": 0, "open": 1, "dismissed": 2}


def _dismissal_ceiling(*entries: dict) -> str | None:
    """The severity a dismissal was actually made at, if one of these
    entries is dismissed. Falls back to the dismissed entry's own severity,
    which is what it was carrying when the tick happened - so state written
    before `dismissed_at_severity` existed still compares correctly.
    """
    for e in entries:
        if e.get("status") == "dismissed":
            return e.get("dismissed_at_severity") or e.get("severity")
    return None


def dedupe_findings(*groups: list[dict]) -> list[dict]:
    """Collapse entries describing the same finding (same fingerprint) into
    one, across every source they can arrive from.

    This is needed because `already_raised_on_this_pr` is advisory: Layer 2
    reviews the whole diff fresh every push and may legitimately re-raise
    something a carried entry already covers. Without this, the same
    finding appears twice - once carried, once fresh - and can even render
    in two different sections at once with two different statuses.

    Precedence, by design:
      - CONTENT comes from the latest group passed in, so callers order
        groups oldest-to-freshest and this push's own judgment wins. Fields
        are taken as a whole dict, never mixed across sources, so a
        finding's `severity` and `l2_severity` always come from the same
        run (mixing them could violate gate.py's severity-floor assertion).
      - STATUS takes the strongest claim by STATUS_RANK: dismissed beats
        open beats resolved. Dismissed is a human decision and must be
        sticky; a resolved inference loses to live evidence that the
        finding is still real.
      - `first_seen` keeps the earliest value any entry carries, so
        provenance isn't reset by a fresh re-raise.

    Entries with no fingerprint have no identity to group on and are passed
    through untouched - grouping them under a shared `None` key would
    collapse unrelated findings into one.
    """
    out: list[dict] = []
    position: dict[str, int] = {}
    for group in groups:
        for f in group:
            fp = f.get("fp")
            if not fp:
                out.append(dict(f))
                continue
            if fp not in position:
                position[fp] = len(out)
                out.append(dict(f))
                continue
            existing = out[position[fp]]
            merged = dict(f)  # later group wins the content
            status = max(
                (existing.get("status"), f.get("status")),
                key=lambda s: STATUS_RANK.get(s, 1),
            )
            ceiling = _dismissal_ceiling(existing, f)
            if ceiling:
                # Carry the ceiling onto the merged entry even when the
                # content came from a fresh finding that never had one -
                # state.apply_dismissals() needs it to refuse re-applying a
                # stale tick to something that has since got worse.
                merged["dismissed_at_severity"] = ceiling
                if severity.RANK.get(merged.get("severity"), 0) > severity.RANK.get(ceiling, 0):
                    # Someone waived a nit; this push judges the same code
                    # worse than what they waived. A dismissal covers what
                    # was dismissed, not an escalation of it.
                    status = "open"
                    merged["resurfaced"] = True
            merged["status"] = status
            first_seen = existing.get("first_seen") or f.get("first_seen")
            if first_seen:
                merged["first_seen"] = first_seen
            out[position[fp]] = merged
    return out


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
    current_blobs = github.pr_file_blobs(repo, pr)

    carried, unchanged = state.carry_forward(prior_state, current_blobs)
    re_anchored, resolved = reanchor_changed_files(prior_state, unchanged)
    dismissed = state.carried_dismissals(prior_state)
    all_carried = carried + re_anchored

    judge_result = judge.judge(client, pr, carried=all_carried)
    new_findings = judge_result.get("findings", [])
    verified = verify.verify(
        client, target.get_diff(pr), target.repo_rules(), {"findings": new_findings}
    )

    new_with_metadata = attach_metadata(verified.get("findings", []))
    for f in all_carried:
        f.setdefault("status", "open")

    # Oldest to freshest: this push's own judgment wins on content, while
    # dedupe_findings() keeps the strongest status claim, so a dismissal
    # survives a fresh re-raise and live evidence overrides a stale
    # "resolved".
    combined = dedupe_findings(resolved, dismissed, all_carried, new_with_metadata)
    base_state = {
        "schema": 1, "head": head_sha, "files": current_blobs,
        "suppressed_count": judge_result.get("suppressed_count", 0),
    }
    # gate.render() happens inside post.post(), against findings freshly
    # reconciled against the live comment - not here, and not before that
    # fetch. Rendering here would use whatever dismissal state existed at
    # the start of this run, stale by the time the comment is written.
    return post.post(repo, pr, combined, base_state)


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
