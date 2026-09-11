#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write on the eval baseline and frozen expected
outputs. An agent that can edit the file its score is compared against will
eventually make a failing change pass by editing that file instead of the
code. Baseline regeneration goes through `make eval-baseline`, human-run only.
"""
import json
import sys

PROTECTED_SUFFIXES = ("evals/baseline.json",)


def is_protected(path: str) -> bool:
    if path.endswith("evals/baseline.json"):
        return True
    return "evals/fixtures/" in path and path.endswith("/expected.json")


def main() -> int:
    payload = json.load(sys.stdin)
    path = payload.get("tool_input", {}).get("file_path", "")
    if is_protected(path):
        print(
            f"Blocked: {path} is a frozen eval file. "
            "Regenerate it with `make eval-baseline` (human-run only), never edit it directly.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
