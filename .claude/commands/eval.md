Run the full eval suite: `python evals/run_eval.py --out build/eval.json`.
Then diff it against evals/baseline.json and report a table of
recall / false positives / verdict accuracy / mean cost per case,
with the delta for each. Flag any case that regressed. Do not edit
baseline.json.
