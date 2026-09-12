"""Memory across pushes (Phase 3). State lives inside the agent's own
sticky PR comment as an HTML-commented JSON block - auditable by anyone
reading the PR, needs no new secret or external store, and survives
force-push because carry_forward() keys off content (blob SHA), not a
commit range. Pure module - no I/O; the caller (post.py) reads/writes the
actual comment.

Shape of the state dict:
    {
        "schema": 1,
        "head": "<sha>",
        "files": {"<path>": "<blob-sha>", ...},
        "findings": [
            {"fp": "<16-hex fingerprint>", "status": "open"|"dismissed"|"resolved",
             "severity": "...", "file": "...", "line": <int|None>,
             "snippet": "...", "summary": "...", "first_seen": "<sha>",
             "verified": bool},
            ...
        ],
    }
"""
from __future__ import annotations

import json
import re

import fingerprint
import severity

MARKER = "pr-review-agent:state:v1"

_STATE_RE = re.compile(rf"<!-- {re.escape(MARKER)}\n(.*?)\n-->", re.S)
_TICK_RE = re.compile(r"^- \[x\] `([0-9a-f]{8})`", re.M | re.I)
_UNTICK_RE = re.compile(r"^- \[ \] `([0-9a-f]{8})`", re.M | re.I)


def render(state: dict) -> str:
    return f"\n<!-- {MARKER}\n{json.dumps(state, separators=(',', ':'))}\n-->"


def parse(comment_body: str) -> dict | None:
    """Corrupt or missing state always degrades to a cold start - never
    raises, never fails the job. A cold start just means every finding on
    this push looks new, which is the safe direction to be wrong in.

    Valid JSON that isn't an object (a list, a bare string, null) counts as
    corrupt: callers do `.get(...)` on the result, so returning it would
    turn "someone mangled the comment" into an AttributeError that fails
    the whole job - exactly what this is supposed to prevent.
    """
    match = _STATE_RE.search(comment_body)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def render_dismissal_line(f: dict) -> str:
    box = "[x]" if f.get("status") == "dismissed" else "[ ]"
    sid = fingerprint.short_id(f.get("fp") or "")
    loc = f["file"] if f.get("file") else "no location"
    if f.get("file") and f.get("line") is not None:
        loc = f"{f['file']}:{f['line']}"
    return f"- {box} `{sid}` {f.get('severity', '')} `{loc}` - {f.get('summary', '')}"


def apply_dismissals(comment_body: str, findings: list[dict]) -> list[dict]:
    """Read the comment's checkbox ticks and mark matching findings
    dismissed. Must be called with the comment body fetched immediately
    before it is next written - see post.py.

    A finding without a fingerprint has no identity a tick could name, so
    it is passed through untouched rather than crashing the run.

    Un-ticking is honoured too: the agent always renders a dismissed
    finding as `- [x]`, so a `- [ ]` line for something state says is
    dismissed can only have come from a person clearing it, and means
    "raise this again". An id appearing both ticked and un-ticked is
    ambiguous, and resolves toward showing the finding rather than hiding
    it.
    """
    ticked = {m.lower() for m in _TICK_RE.findall(comment_body)}
    unticked = {m.lower() for m in _UNTICK_RE.findall(comment_body)}
    dismissed_ids = ticked - unticked
    out = []
    for f in findings:
        f = dict(f)
        fp = f.get("fp")
        if fp and f.get("status") == "dismissed" and fingerprint.short_id(fp).lower() in unticked:
            f["status"] = "open"
            f.pop("dismissed_at_severity", None)
            out.append(f)
            continue
        if fp and fingerprint.short_id(fp).lower() in dismissed_ids:
            ceiling = f.get("dismissed_at_severity")
            if ceiling and severity.RANK.get(f.get("severity"), 0) > severity.RANK.get(ceiling, 0):
                # The tick is still sitting in the comment text from when
                # this was a nit, but the finding has since been judged
                # worse than what was waived. Re-applying the tick here
                # would silently undo run.dedupe_findings()'s resurfacing
                # and suppress, say, a credential leak because someone once
                # waved off a style nit on the same line. Set the status
                # outright rather than only tagging it, so this holds even
                # when dedupe_findings() wasn't the one to spot it.
                f["status"] = "open"
                f["resurfaced"] = True
            else:
                f["status"] = "dismissed"
                # Record what was actually waived. Severity is deliberately
                # not part of a fingerprint, so without this a dismissal
                # would keep applying at any severity.
                f.setdefault("dismissed_at_severity", f.get("severity"))
        out.append(f)
    return out


def carry_forward(prior_state: dict | None, current_blobs: dict[str, str]) -> tuple[list[dict], set[str]]:
    """Which prior OPEN findings survive to this push, and which files are
    untouched since the prior run (content-addressed by blob SHA, so this
    survives rebase/squash/force-push - a SHA-range diff would not).
    Content-addressed rather than commit-addressed deliberately: a
    force-push changes every commit SHA but not an unedited file's blob SHA.

    Dismissed findings are deliberately NOT returned here - they are not
    tied to a file being unchanged, and are collected by
    carried_dismissals() instead.
    """
    if not prior_state:
        return [], set()
    prior_files = prior_state.get("files", {})
    unchanged = {path for path, sha in current_blobs.items() if prior_files.get(path) == sha}
    carried = [
        f for f in prior_state.get("findings", [])
        if f.get("file") in unchanged and f.get("status") == "open"
    ]
    return carried, unchanged


def carried_dismissals(prior_state: dict | None) -> list[dict]:
    """Every finding a human has dismissed, carried forward unconditionally.

    A dismissal is a human decision keyed to a fingerprint, and the
    fingerprint already encodes the code it was about - if that code
    changes materially the fingerprint changes with it and the finding
    comes back as new, which is the correct outcome. So there is no file
    or freshness condition to apply here; the only way a dismissal should
    stop applying is the fingerprint no longer matching.

    Keeping these in state is what makes dismissal durable. An earlier
    version dropped them, and dismissal survived only as long as the
    rendered `- [x]` line kept being re-emitted - so a push that didn't
    re-raise the finding silently lost the tick, and a later push that
    raised it again showed it as open.
    """
    if not prior_state:
        return []
    return [f for f in prior_state.get("findings", []) if f.get("status") == "dismissed"]


def resolve(entry: dict, new_content: str, window: int = 30) -> tuple[str, int | None]:
    """Re-anchor a carried finding whose file changed. Search for the
    original snippet within `window` lines of the recorded line first,
    widen to the whole file if not found there, and mark it resolved
    (code is gone) only if the snippet can't be found anywhere.

    The snippet is usually several lines (callers pass surrounding context,
    not just the one flagged line), so the search slides a same-sized
    window of lines rather than checking one line at a time - a multi-line
    normalized target can never be a substring of one normalized line.

    A finding with no snippet to search for (a repo/file-level claim such
    as "this module has no tests", where `line` is null) is NOT resolvable
    by this mechanism. It stays open at its recorded line rather than being
    declared resolved: "I have no way to check" and "the code is gone" are
    different answers, and only the caller knowing the file itself is gone
    settles it. Treating them the same silently dropped real file-level
    findings the moment anything in the file changed.
    """
    original_snippet = entry.get("snippet") or ""
    target = fingerprint.normalize_snippet(original_snippet)
    if not target:
        return "open", entry.get("line")
    lines = new_content.splitlines()
    span = max(1, len(original_snippet.splitlines()))

    def _search(indices):
        for i in indices:
            end = i + span
            if end > len(lines):
                continue
            window_text = fingerprint.normalize_snippet("\n".join(lines[i:end]))
            if target in window_text:
                return i + (span // 2) + 1  # roughly the window's center, 1-indexed
        return None

    old_line = entry.get("line")
    if old_line is not None:
        near = range(max(0, old_line - 1 - window), min(len(lines), old_line - 1 + window + 1))
        found = _search(near)
        if found is not None:
            return "open", found

    found = _search(range(len(lines)))
    if found is not None:
        return "open", found
    return "resolved", None
