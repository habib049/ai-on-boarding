"""Every call that leaves this tool for GitHub, in one place.

It was previously split: run.py and post.py each carried their own copy of
the same `gh api` helper and each fetched the PR's comments separately, so
one review made two identical round-trips and a test that stubbed one
module silently left the other making real calls.

Keeping the surface here means there is a single place to stub in tests, a
single place to add rate-limit handling, and one answer to "what does this
tool do to a repository" - which for a bot with `pull-requests: write` is
worth being able to answer by reading one file.
"""
from __future__ import annotations

import json
import subprocess


class GitHubError(RuntimeError):
    pass


def _gh_json(*args: str):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise GitHubError(f"gh {' '.join(args)} failed: {result.stderr}")
    return json.loads(result.stdout)


def pr_comments(repo: str, pr: str) -> list[dict]:
    return _gh_json("api", f"repos/{repo}/issues/{pr}/comments")


def pr_file_blobs(repo: str, pr: str) -> dict[str, str]:
    """Path -> blob SHA for every file in the PR. Content-addressed, so it
    survives rebase and force-push where a commit range would not.
    """
    files = _gh_json("api", f"repos/{repo}/pulls/{pr}/files", "--paginate")
    return {f["filename"]: f["sha"] for f in files if "sha" in f}


def update_comment(repo: str, comment_id, body: str) -> None:
    subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/comments/{comment_id}", "-X", "PATCH", "--input", "-"],
        input=json.dumps({"body": body}), text=True, check=True,
    )


def create_comment(pr: str, body: str) -> None:
    subprocess.run(["gh", "pr", "comment", pr, "--body", body], check=True)
