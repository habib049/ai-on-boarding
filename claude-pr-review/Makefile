.PHONY: eval eval-baseline

# Run every fixture, write build/eval.json. No live GitHub calls (fixtures
# are frozen), but real Anthropic calls for any non-lint-sourced finding.
eval:
	python3 evals/run_eval.py --out build/eval.json

# Regenerate the scored baseline every later phase diffs against. Human-run
# only - the protect_eval.py hook blocks Claude's own Edit/Write tool calls
# on evals/baseline.json, but a `make` invocation isn't one of those calls,
# so this still works from a human terminal or an explicit human instruction.
eval-baseline:
	python3 evals/run_eval.py --out evals/baseline.json
