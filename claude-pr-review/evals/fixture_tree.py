"""Stage a fixture's file tree into the repo for the duration of a run.

This exists because Layer 3 reads the *working tree* through tools.py while
being handed a fixture's diff. Without staging, the two disagree: an early
version of the harness ran fixtures whose diff added files that weren't in
the worktree, so every read_file failed, Layer 3 concluded the described
code didn't exist, and dropped findings for that reason rather than any
reason the fixture was written to test. The results looked like prompt bugs
and weren't.

(That failure is also why tools.execute() now flags a failed read as
`is_error` rather than returning "No such file" as ordinary content - the
model was reading a tool failure as a fact about the repository.)
"""
from __future__ import annotations

import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

from target import REPO_ROOT


@contextmanager
def materialize(fixture_dir: Path, subdir: str = "snapshot"):
    """Stage `fixture_dir/subdir` into the repo, then remove it again.

    Refuses to touch a path that already exists - a fixture is never
    allowed to overwrite real repository content.
    """
    source_root = fixture_dir / subdir
    staged: list[Path] = []
    if not source_root.is_dir():
        print(f"[eval] {fixture_dir}/{subdir}/ missing - Layer 3 will read a tree that does not "
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
                raise FileExistsError(f"fixture would overwrite existing repo file: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            staged.append(destination)
        print(f"[eval] staged {len(staged)} fixture file(s) into {REPO_ROOT}", file=sys.stderr)
        yield
    finally:
        for path in staged:
            path.unlink(missing_ok=True)
        print(f"[eval] removed {len(staged)} staged fixture file(s)", file=sys.stderr)
