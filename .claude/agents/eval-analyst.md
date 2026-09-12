---
name: eval-analyst
description: Run the pr-review-agent eval suite and summarize the results. Use instead of reading evals/run_eval.py's raw output directly - it is long and noisy, and this keeps that out of the main thread's context. Invoke whenever a phase's changes need to be scored against the eval baseline.
tools: Bash, Read
model: haiku
---

Run `python evals/run_eval.py --out build/eval.json` from the `claude-pr-review`
directory, then compare it against `evals/baseline.json`.

Report only:
- A table: case id, recall, false positives, verdict correct (y/n), cost (USD).
- A list of case IDs that regressed relative to baseline (worse recall, a new
  false positive, or a flipped verdict).
- Nothing else - no raw JSON, no per-tool-call narration.
