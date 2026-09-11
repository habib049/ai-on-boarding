"""Layer 4: render Layer 3's verified findings as the Ready to merge: yes/no
verdict - a finding blocks only if it still carries a citation and is
CRITICAL or MAJOR. That blocking condition is unchanged by the three-way
split below: an uncited or citation-rejected CRITICAL/MAJOR, and any
unverified finding, get their own "worth a look" section instead of being
buried in the same bucket as a MINOR typo - a reviewer skimming the nits
section should not have to notice a live CRITICAL hiding in it. Exits
non-zero on "no" so CI can fail the check.

Also enforces invariant 4 (CLAUDE.md): Layer 3 may escalate a severity, it
may never downgrade one. A finding carrying `l2_severity` (verify.py sets it
on every finding it processes) below its final `severity` is fine, expected
even; the reverse is a hard failure, not a warning - this is the code-level
backstop for a rule that would otherwise depend entirely on the verify.md
prompt holding.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fingerprint
import severity
import state

BLOCKING_SEVERITIES = {"CRITICAL", "MAJOR"}


def _assert_severity_floor(all_findings: list[dict]) -> None:
    for f in all_findings:
        final_rank = severity.RANK.get(f.get("severity"), 0)
        l2_rank = severity.RANK.get(f.get("l2_severity", f.get("severity")), 0)
        assert final_rank >= l2_rank, (
            f"invariant 4 violated: {f.get('file')}:{f.get('line')} final severity "
            f"{f.get('severity')!r} ranks below Layer 2's {f.get('l2_severity')!r}"
        )


def _line(f: dict) -> str:
    if not f.get("file"):
        loc = "no location"
    elif f.get("line") is None:
        loc = f["file"]
    else:
        loc = f"{f['file']}:{f['line']}"
    tag = " [unverified]" if f.get("unverified") else ""
    return f"- [{f['severity']}]{tag} {f['summary']} ({loc})"


def render(findings: dict) -> tuple[str, bool]:
    all_findings = findings.get("findings", [])
    _assert_severity_floor(all_findings)

    # Phase 3 (memory across pushes): a carried finding a human ticked
    # dismissed, or one state.resolve() couldn't re-anchor because the code
    # is gone, is out of the blocking/serious/nits computation entirely -
    # it's neither a new concern nor a live one, just a record.
    dismissed = [f for f in all_findings if f.get("status") == "dismissed"]
    resolved = [f for f in all_findings if f.get("status") == "resolved"]
    live = [f for f in all_findings if f not in dismissed and f not in resolved]

    blocking = [
        f for f in live
        if f.get("citation") and f.get("severity") in BLOCKING_SEVERITIES
    ]
    serious = [
        f for f in live
        if f not in blocking and (f.get("severity") in BLOCKING_SEVERITIES or f.get("unverified"))
    ]
    nits = [f for f in live if f not in blocking and f not in serious]
    ready = not blocking

    lines = ["# PR Review Verdict", ""]
    if blocking:
        lines.append("## Blocking (%d)" % len(blocking))
        for f in blocking:
            lines.append(_line(f) + f" - cites: {f['citation']}")
        lines.append("")
    if serious:
        lines.append("## Unblocked but worth a look (%d)" % len(serious))
        for f in serious:
            lines.append(_line(f))
        lines.append("")
    if nits:
        lines.append("## Nits (%d)" % len(nits))
        for f in nits:
            # A nit carrying a fingerprint (Phase 3: memory across pushes)
            # renders as a checkbox - ticking it dismisses the finding on
            # the next run. Blocking/serious findings never get this
            # treatment: a checkbox isn't how a real concern gets waived.
            if f.get("fp"):
                lines.append(state.render_dismissal_line(f))
            else:
                lines.append(_line(f))
        if any(f.get("fp") for f in nits):
            lines.append("_Tick a box to dismiss that finding; the reviewer won't raise it again._")
        lines.append("")
    if dismissed:
        lines.append("<details><summary>Previously dismissed (%d)</summary>" % len(dismissed))
        lines.append("")
        for f in dismissed:
            lines.append(state.render_dismissal_line(f))
        lines.append("")
        lines.append("</details>")
        lines.append("")
    if resolved:
        lines.append("<details><summary>Resolved (%d)</summary>" % len(resolved))
        lines.append("")
        for f in resolved:
            lines.append(f"- `{fingerprint.short_id(f['fp'])}` {f.get('severity', '')} {f.get('summary', '')} (code no longer found)")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    if not all_findings:
        lines.append("No findings.")
        lines.append("")
    suppressed = findings.get("suppressed_count") or 0
    if suppressed:
        lines.append(f"_{suppressed} additional finding(s) suppressed by the findings cap._")
    unverified_count = sum(1 for f in all_findings if f.get("unverified"))
    if unverified_count:
        lines.append(f"_Verification unavailable for {unverified_count} finding(s) - see [unverified] above._")
    if suppressed or unverified_count:
        lines.append("")
    lines.append(f"**Ready to merge: {'yes' if ready else 'no'}**")
    return "\n".join(lines), ready


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", type=Path, required=True, help="Path to verify.py's output JSON")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    findings = json.loads(args.findings.read_text())
    report, ready = render(findings)

    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
