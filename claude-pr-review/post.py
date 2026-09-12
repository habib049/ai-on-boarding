"""Post the run's verdict as a sticky PR comment - find-and-PATCH the prior
one by state.MARKER rather than POSTing a new comment every push, so ten
pushes leave one comment, not ten.

Ordering matters (3.6): the comment body is fetched fresh in post(), as the
LAST read before this job decides what to write - not reused from the copy
run.py fetched earlier to compute carry-forward. If a human ticks a
dismissal checkbox after this job started but before it finishes, a stale
copy of the body would silently overwrite that tick with an un-dismissed
version.

The earlier version of this module reconciled dismissals into the *stored
state* here but rendered the human-visible verdict text and exit code
*before* this fetch, in run.py - so a tick applied on this exact push made
the stored state say "dismissed" while the posted text and CI exit code for
that same push still said "no"/blocking. gate.render() now happens in here,
against the reconciled findings, so there is exactly one render per run and
it reflects the same data that gets written.
"""
from __future__ import annotations

import gate
import github
import severity
import state

MAX_COMMENT_CHARS = 65_536  # GitHub's hard cap on an issue comment body
TRUNCATION_NOTICE = "\n\n_Verdict truncated to fit GitHub's comment size limit._\n"

# Alias kept so callers catching a failure to reach GitHub don't need to
# know which module raises it.
PostError = github.GitHubError


def _is_bot(comment: dict) -> bool:
    return str((comment.get("user") or {}).get("type", "")).lower() == "bot"


def find_existing_comment_id(comments: list[dict]):
    """The sticky comment to update, or None to post a fresh one.

    Takes the LAST marker-bearing comment, preferring one authored by a
    bot: quoting a comment on GitHub copies its raw body, HTML comment and
    all, so a human quoting the verdict produces a second comment carrying
    the marker. Taking the first match would make the agent start editing
    that person's comment and reading its (stale) state as truth.
    """
    matches = [c for c in comments if state.MARKER in (c.get("body") or "")]
    if not matches:
        return None
    bot_matches = [c for c in matches if _is_bot(c)]
    return (bot_matches or matches)[-1]["id"]


def build_comment_body(verdict_report: str, new_state: dict) -> str:
    return verdict_report + "\n" + state.render(new_state)


STORED_SUMMARY_CHARS = 200


def _without_status(s: dict, status: str) -> dict:
    out = dict(s)
    out["findings"] = [f for f in s.get("findings", []) if f.get("status") != status]
    return out


def _with_trimmed_summaries(s: dict) -> dict:
    out = dict(s)
    out["findings"] = [
        {**f, "summary": f["summary"][:STORED_SUMMARY_CHARS] + "..."}
        if len(f.get("summary") or "") > STORED_SUMMARY_CHARS else f
        for f in s.get("findings", [])
    ]
    return out


def fit_to_comment_limit(new_state: dict) -> tuple[str, str, bool]:
    """Render the verdict and fit it under GitHub's comment cap.

    The ladder, cheapest loss first:
      1. as-is
      2. drop resolved entries (the plan's stated first move - they're a
         record of code that's already gone)
      3. trim stored summaries to STORED_SUMMARY_CHARS - the state block
         exists to carry identity and status, not prose, so shedding words
         costs far less than losing entries
      4. drop dismissed entries - last, because each one is a human
         decision that can't be recovered
      5. truncate the human-readable report, never the JSON: a half-written
         state block parses as corrupt next run, which would throw away
         every remaining dismissal along with it

    Blocking findings are never dropped, so `ready` is unaffected by any
    degradation here.
    """
    working = dict(new_state)
    stages = (
        lambda s: s,
        lambda s: _without_status(s, "resolved"),
        _with_trimmed_summaries,
        lambda s: _without_status(s, "dismissed"),
    )
    for transform in stages:
        working = transform(working)
        report, ready = gate.render(working)
        body = build_comment_body(report, working)
        if len(body) <= MAX_COMMENT_CHARS:
            return body, report, ready

    # Cut the prose, keep the (already trimmed) state block whole.
    tail = "\n" + state.render(working)
    budget = MAX_COMMENT_CHARS - len(tail) - len(TRUNCATION_NOTICE)
    if budget > 0:
        return report[:budget] + TRUNCATION_NOTICE + tail, report, ready

    # Only reachable if the trimmed state block alone still doesn't fit
    # (hundreds of retained entries). Shed entries rather than emit a body
    # GitHub will reject outright - a rejected write means no verdict and
    # no state at all. Most severe first, so what survives is what a
    # reviewer most needs to see.
    findings = sorted(
        working.get("findings", []),
        key=lambda f: severity.RANK.get(f.get("severity"), 0),
        reverse=True,
    )
    while findings and budget <= 0:
        findings.pop()
        working = {**working, "findings": findings}
        tail = "\n" + state.render(working)
        budget = MAX_COMMENT_CHARS - len(tail) - len(TRUNCATION_NOTICE)
    report, ready = gate.render(working)
    return report[:max(0, budget)] + TRUNCATION_NOTICE + tail, report, ready


def post(repo: str, pr: str, combined_findings: list[dict], base_state: dict) -> dict:
    """Fetch the live comment list (the read this whole ordering exists
    for), reconcile any dismissal ticks against the current body, render
    the verdict from the reconciled findings, then PATCH the existing
    sticky comment or POST a new one. Returns {"report": str, "ready": bool}
    - the caller's printed output and exit code must come from here, never
    from a render computed before this reconciliation.
    """
    comments = github.pr_comments(repo, pr)
    comment_id = find_existing_comment_id(comments)
    live_body = next((c["body"] for c in comments if c.get("id") == comment_id), "")

    reconciled = state.apply_dismissals(live_body, combined_findings)
    new_state = dict(base_state)
    new_state["findings"] = reconciled
    body, report, ready = fit_to_comment_limit(new_state)

    if comment_id:
        github.update_comment(repo, comment_id, body)
    else:
        github.create_comment(pr, body)
    return {"report": report, "ready": ready}
