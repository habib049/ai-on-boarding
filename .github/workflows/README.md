# Claude PR Review (GitHub Action)

Runs the real Claude Code CLI, headless, inside GitHub Actions - not a custom script calling the
API. `claude-pr-review.yml` reviews every PR (`opened`, `synchronize`) in three layers and posts
the verdict as PR comments via `gh pr comment` / inline review comments.

This is the alternative to the standalone Python agent on the `pr-review-agent` branch: same
three-layer shape (lint, judge, verify), but Layers 2 and 3 are Claude Code
[skills](../../.claude/skills/) run through Anthropic's
[`claude-code-action`](https://github.com/anthropics/claude-code-action) instead of hand-rolled
prompts and orchestration calling the API directly.

| Layer | What | Where |
|---|---|---|
| 1 | Lint the PR's changed Python files. Mechanical, always right about what it covers - not worth a model call. | plain `ruff` step in the workflow |
| 2 | Judge the diff for architectural fit, convention compliance, correctness/completeness, and blast radius. Excludes anything Layer 1 already flagged. Writes findings to a file, doesn't post. | `.claude/skills/pr-judge/`, `--model claude-opus-5` |
| 3 | Independently re-check every Layer 2 finding's citation and failure scenario before it can block a merge. Posts the final `Ready to merge: yes/no` verdict. | `.claude/skills/pr-verify/`, `--model claude-haiku-4-5-20251001` |

Putting Layers 2 and 3 in skills (rather than inlining their instructions in the workflow prompt)
keeps them editable and reviewable on their own, the same reason `pr-review-agent`'s prompts live
in their own `prompts/*.md` files rather than as Python strings - and it means a local `claude`
session gets the identical judge/verify behavior these skills describe, not a CI-only prompt.

## One-time setup

1. Generate a subscription OAuth token locally (Pro/Max plan - uses subscription quota, not API
   billing):
   ```
   claude setup-token
   ```

2. Add it as a repo secret named `CLAUDE_CODE_OAUTH_TOKEN`
   (Settings -> Secrets and variables -> Actions -> New repository secret).

3. Open a PR. The workflow runs automatically on `opened`/`synchronize`.

No Claude GitHub App install is needed: each `claude-code-action` step is given
`github_token: ${{ secrets.GITHUB_TOKEN }}` directly, so it skips the action's default behavior
of exchanging a GitHub Actions OIDC token for a Claude App installation token - which otherwise
requires both `id-token: write` and the app installed. Passing the ambient `GITHUB_TOKEN`
sidesteps both requirements at the cost of the app's extra features (e.g. commit signing), which
this workflow doesn't use anyway (it only comments, never pushes commits).

## Why this shape

- **Real Claude Code, not a reimplementation.** The action checks out the repo and runs the
  actual CLI, so it reads `CLAUDE.md` and `.claude/skills/` the same way a local session would -
  no separate prompt-engineering surface to keep in sync with this repo's conventions.
- **Subscription auth, not an API key.** `claude_code_oauth_token` (from `claude setup-token`)
  bills against Pro/Max quota instead of pay-per-token API usage - this is a learning exercise,
  not a system meant to run indefinitely against metered billing.
- **Comments only, no write access to code.** Each step's `claude_args` scopes its tools to what
  that layer needs: Layer 2 (judge) gets `Read`/`Grep`/`Glob`/`Write(build/**)` (its findings file
  only) and `gh pr diff`/`gh pr view` to search the repo, plus an explicit `--disallowedTools` for
  the comment-posting tools - it never posts. Layer 3 (verify) gets the same read tools plus
  `gh pr comment` and the inline-comment MCP tool, since it's the one that posts the verdict.
  Neither step can push commits.
- **Verify runs on a cheaper model.** Layer 3 is a bounded recheck of Layer 2's existing findings
  against the diff and rules, not open-ended judgment, so `--model claude-haiku-4-5-20251001`
  covers it without paying for Layer 2's model twice.
- **Least-privilege permissions.** No `id-token: write` - that permission is only for OIDC
  federation to a cloud provider (Bedrock/Vertex), which this setup doesn't use; the OAuth token
  auths directly, so the job only needs `contents: read` and `pull-requests: write`.
- **Prompt-injection awareness.** The action already strips common hidden-instruction vectors
  (HTML comments, invisible characters) from PR content, but the prompt also explicitly tells
  Claude that the diff/comments it's reviewing are data, not instructions - belt-and-suspenders
  against a PR description or comment trying to steer the review.

## Known gaps

- Inline comment *classification* (auto-resolving low-confidence comments) requires
  `anthropic_api_key`; with only an OAuth token, comments post directly and unconfirmed ones are
  not filtered out the same way.
- No path-filtering, no separate handling for external contributors yet - every PR gets the same
  full review, including PRs from forks (`pull_request` fires for them too). Fork PRs don't get
  repo secrets by default, though, so `CLAUDE_CODE_OAUTH_TOKEN` is empty and Layers 2/3 fail
  rather than silently skipping - there's no gate here that would give a fork PR a degraded (but
  passing) review instead of a failed job.
