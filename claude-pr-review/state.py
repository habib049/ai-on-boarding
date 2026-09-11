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

MARKER = "pr-review-agent:state:v1"

_STATE_RE = re.compile(rf"<!-- {re.escape(MARKER)}\n(.*?)\n-->", re.S)
_TICK_RE = re.compile(r"^- \[x\] `([0-9a-f]{8})`", re.M | re.I)


def render(state: dict) -> str:
    return f"\n<!-- {MARKER}\n{json.dumps(state, separators=(',', ':'))}\n-->"


def parse(comment_body: str) -> dict | None:
    """Corrupt or missing state always degrades to a cold start - never
    raises, never fails the job. A cold start just means every finding on
    this push looks new, which is the safe direction to be wrong in.
    """
    match = _STATE_RE.search(comment_body)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def render_dismissal_line(f: dict) -> str:
    box = "[x]" if f.get("status") == "dismissed" else "[ ]"
    sid = fingerprint.short_id(f["fp"])
    loc = f"{f['file']}:{f['line']}" if f.get("line") is not None else f.get("file", "no location")
    return f"- {box} `{sid}` {f.get('severity', '')} `{loc}` - {f.get('summary', '')}"


def apply_dismissals(comment_body: str, findings: list[dict]) -> list[dict]:
    """Read the comment's checkbox ticks and mark matching findings
    dismissed. Must be called with the comment body fetched immediately
    before it is next written - see post.py.
    """
    dismissed_ids = set(m.lower() for m in _TICK_RE.findall(comment_body))
    out = []
    for f in findings:
        f = dict(f)
        if fingerprint.short_id(f["fp"]).lower() in dismissed_ids:
            f["status"] = "dismissed"
        out.append(f)
    return out


def carry_forward(prior_state: dict | None, current_blobs: dict[str, str]) -> tuple[list[dict], set[str]]:
    """Which prior findings survive to this push, and which files are
    untouched since the prior run (content-addressed by blob SHA, so this
    survives rebase/squash/force-push - a SHA-range diff would not).
    Content-addressed rather than commit-addressed deliberately: a
    force-push changes every commit SHA but not an unedited file's blob SHA.
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


def resolve(entry: dict, new_content: str, window: int = 30) -> tuple[str, int | None]:
    """Re-anchor a carried finding whose file changed. Search for the
    original snippet within `window` lines of the recorded line first,
    widen to the whole file if not found there, and mark it resolved
    (code is gone) only if the snippet can't be found anywhere.

    The snippet is usually several lines (callers pass surrounding context,
    not just the one flagged line), so the search slides a same-sized
    window of lines rather than checking one line at a time - a multi-line
    normalized target can never be a substring of one normalized line.
    """
    original_snippet = entry.get("snippet", "")
    target = fingerprint.normalize_snippet(original_snippet)
    if not target:
        return "resolved", None
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
