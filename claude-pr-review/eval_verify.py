"""Run verify.py against a saved fixture instead of a live PR, so verify.md
changes can be tested repeatably without a paid CI cycle or a real GitHub
PR. Still spends real API money per trial - nothing here runs itself.

A fixture is a directory with diff.txt (unified diff, any format target.py
would have produced), rules.json ({"path": "contents", ...}, target.py's
repo_rules() shape), findings.json (judge.py's output shape, the
{"findings": [...]} Layer 2 would have produced), and files/ - the
post-change contents of every file the diff touches, laid out at their
repo-relative paths.

files/ exists because Layer 3 reads the *working tree* through tools.py
while being handed a fixture's diff. Without it the two disagree: an early
version of this harness ran fixtures whose diff added files that weren't
in the worktree, so every read_file returned "No such file", Layer 3
concluded the described code didn't exist, and dropped findings for that
reason rather than any reason the fixture was written to test. The results
looked like prompt bugs and weren't. materialize() stages files/ into the
repo for the duration of the run and removes them afterwards, so the tree
Layer 3 reads matches the diff it was given.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import anthropic

import verify
from target import REPO_ROOT


@contextmanager
def materialize(fixture_dir: Path, subdir: str = "files"):
    """Stage a fixture's file tree into the repo, then remove it again.

    Refuses to touch a path that already exists - a fixture is never allowed
    to overwrite real repository content. `subdir` defaults to "files" (this
    module's own fixtures); evals/run_eval.py's fixtures use "snapshot".
    """
    source_root = fixture_dir / subdir
    staged: list[Path] = []
    if not source_root.is_dir():
        print(f"[eval] {fixture_dir}/files/ missing - Layer 3 will read a tree that does not "
              f"match the fixture diff, and findings may be dropped for that reason alone.",
              file=sys.stderr)
        yield
        return

    try:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file():
                continue
            destination = REPO_ROOT / source.relative_to(source_root)
            if destination.exists():
                raise FileExistsError(
                    f"fixture would overwrite existing repo file: {destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            staged.append(destination)
        print(f"[eval] staged {len(staged)} fixture file(s) into {REPO_ROOT}", file=sys.stderr)
        yield
    finally:
        for path in staged:
            path.unlink(missing_ok=True)
        print(f"[eval] removed {len(staged)} staged fixture file(s)", file=sys.stderr)


def load_fixture(fixture_dir: Path) -> tuple[str, dict, dict]:
    diff = (fixture_dir / "diff.txt").read_text()
    rules = json.loads((fixture_dir / "rules.json").read_text())
    findings = json.loads((fixture_dir / "findings.json").read_text())
    return diff, rules, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Path to a fixture directory")
    parser.add_argument("--trials", type=int, default=1, help="Run this many times, for variance")
    args = parser.parse_args()

    diff, rules, findings = load_fixture(args.fixture)
    client = anthropic.Anthropic()

    with materialize(args.fixture):
        for trial in range(1, args.trials + 1):
            try:
                result = verify.verify(client, diff, rules, findings)
            except Exception as exc:
                print(f"=== {args.fixture.name} trial {trial}/{args.trials}: CRASHED: {exc} ===",
                      file=sys.stderr)
                continue
            print(f"=== {args.fixture.name} trial {trial}/{args.trials}: "
                  f"{len(result['findings'])}/{len(findings.get('findings', []))} findings kept ===")
            print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
