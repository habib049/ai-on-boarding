"""Phase 0 eval harness: run Layer 3 (verify.py) + Layer 4 (gate.py) against
every frozen fixture in evals/fixtures/ and score the result with scorer.py.

Fixtures are frozen artifacts - this never regenerates a fixture's diff.txt
and never reaches the network for repo content (diff.txt/rules.json/
findings.json are read as-is; snapshot/ is staged into the real repo tree
for the run and removed after, the same pattern eval_verify.py already uses
for its one hand-written scenario).

Layer 1 (lint.py) and Layer 2 (judge.py) are not exercised here: both are
tightly coupled to target.py's live git/gh calls to resolve "what changed",
which a frozen fixture has no equivalent of. lint.py is pure ruff and needs
no eval; judge.py's own harness is a separate, later piece of work. What
this suite scores is the part that decides whether a citation survives and
whether the gate's verdict is right - the part Phase 1/2 change the most.

--dry-run stubs the Anthropic client so harness bugs (fixture loading,
staging, scoring, JSON shape) can be found without spending a token.
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # claude-pr-review/ - gate.py, verify.py, etc.

import anthropic

import gate
import scorer
import verify
from eval_verify import materialize

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _stub_response(findings: list[dict] | None = None):
    payload = json.dumps({"findings": findings or []})
    return types.SimpleNamespace(
        stop_reason="end_turn",
        content=[types.SimpleNamespace(type="text", text=payload)],
    )


class _StubStream:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return _stub_response()


class _StubMessages:
    def create(self, **kwargs):
        return _stub_response()


class _StubBetaMessages:
    def stream(self, **kwargs):
        return _StubStream()


class _StubClient:
    """Fakes just enough of anthropic.Anthropic for agent.run() - always
    zero findings, whichever of the two request paths (plain vs. task-budget
    streaming) the caller takes. Exercises harness mechanics only, never
    prompt quality.
    """

    def __init__(self):
        self.messages = _StubMessages()
        self.beta = types.SimpleNamespace(messages=_StubBetaMessages())


def load_fixture(fixture_dir: Path) -> tuple[str, dict, dict, dict]:
    diff = (fixture_dir / "diff.txt").read_text()
    rules = json.loads((fixture_dir / "rules.json").read_text())
    findings = json.loads((fixture_dir / "findings.json").read_text())
    expected = json.loads((fixture_dir / "expected.json").read_text())
    return diff, rules, findings, expected


def run_case(client, fixture_dir: Path) -> dict:
    diff, rules, findings, expected = load_fixture(fixture_dir)
    with materialize(fixture_dir, subdir="snapshot"):
        verified = verify.verify(client, diff, rules, findings)
    _, ready = gate.render(verified)
    produced = {"findings": verified["findings"], "verdict": "yes" if ready else "no", "cost": None}
    return scorer.score_case(produced, expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Stub the Anthropic client - no tokens spent")
    args = parser.parse_args()

    client = _StubClient() if args.dry_run else anthropic.Anthropic()

    fixture_dirs = sorted(d for d in FIXTURES_DIR.iterdir() if d.is_dir())
    case_scores = {}
    for fixture_dir in fixture_dirs:
        case_scores[fixture_dir.name] = run_case(client, fixture_dir)

    result = {"cases": case_scores, "summary": scorer.summarize(case_scores)}
    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
