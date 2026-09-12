# Citation contract

A finding blocks a merge only if it carries a citation **and** its severity is CRITICAL or MAJOR
(`gate.py`'s `BLOCKING_SEVERITIES`). This file is the authoritative list of what counts as a
citation. CLAUDE.md's invariant 6 points here: **adding a form means editing this file in the same
commit.**

The point of the citation rule is that the bar is written down. An undocumented special case
erodes that even when the case itself is correct — which is exactly what happened with
`ruff:<code>`, introduced as a fourth form without being recorded anywhere.

## Accepted forms

| Form | Example | Checked by |
|---|---|---|
| Requirement | `### Requirement: User signs up with email` from `openspec/specs/<capability>/spec.md` | model (`NEEDS_MODEL`) |
| Named failing test | `test_signin_rejects_bad_password` | deterministic — the name must exist in the repo's test index |
| Quoted convention | `CLAUDE.md: "Security-sensitive behaviour ... needs a test that asserts it directly"` | deterministic — the quoted text must appear in the convention docs |
| Ruff rule | `ruff:F401` | deterministic — ruff already ran and produced it |

Convention text may be cited from `CLAUDE.md`, `openspec/config.yaml`, `AGENTS.md`, or
`sdd_django_demo/CLAUDE.md` — whatever `target.repo_rules()` loads.

### On `ruff:<code>`

It is legitimate, and arguably the strongest form: it is the only citation that can be
mechanically re-derived by re-running a command. Quoted convention text can be paraphrased or
invented; a rule code cannot. A finding carrying `source: "lint"` skips Layer 3 entirely for this
reason — ruff is ground truth, not a model claim to re-check.

## How citations are verified

`citations.precheck()` resolves the deterministic forms in code, for free, before any model call:

- `CONFIRMED` — skip the model, the citation is valid.
- `REJECTED` — the citation is false. **The finding is kept**, with `citation` set to null, which
  routes it to the non-blocking "worth a look" section. A model hallucinating a citation on a real
  security bug should lose the citation, not the bug.
- `NEEDS_MODEL` — not mechanically decidable; Layer 3 checks it.

Layer 3 can only confirm or reject a citation (`citation_holds`) and *escalate* a severity
(`escalate_to`). It has no field to assign a final severity — see `agent.VERIFICATION_SCHEMA` and
invariant 4.

## Severity map for ruff codes

From `severity.py`. Longest-prefix match: `F821` hits `F82` before the generic `F`.

| Prefix | Severity | What it covers |
|---|---|---|
| `S` | CRITICAL | bandit / security - hardcoded secrets, `eval`, injection |
| `F82` | MAJOR | undefined name |
| `F81` | MAJOR | redefinition |
| `B` | MAJOR | bugbear |
| `F` | MINOR | remaining pyflakes (`F401` unused import, etc.) |
| `E`, `I` | MINOR | pycodestyle, import sorting |

Anything unrecognised defaults to MINOR. A blanket MAJOR was the original behaviour and it made
an unused import fail the check identically to a broken auth path.

**Every prefix in this table must be one `ruff.toml` actually selects.** It originally mapped
`S -> CRITICAL` and `B -> MAJOR` while selecting only `E`/`F`/`I`, so neither could ever fire: the
map advertised a security tier the linter was never asked to check, and Layer 1 could not produce
a finding above MAJOR. A hardcoded secret - the top of this tool's own severity definition - was
invisible to the one layer that is deterministic, free, and immune to a model changing its mind.
`S` and `B` are now selected, and `test_lint_layer.py` asserts the map and the config stay in
sync. (`W` and `N` were dropped rather than selected: both map to MINOR, which is already the
default for an unrecognised code, so listing them changed nothing either way.)

Noise is handled by exclusion rather than by not looking: `S101` (assert-used, 619 hits across
this repo's assert-based tests), `S603`/`S607` (fire on every legitimate `subprocess` call - this
tool shells out to `gh`, `rg` and `ruff` by design), and the password rules scoped away from test
files, where fake credentials are the correct way to write the test. That takes the repo from 698
raw S/B hits to 2 real ones.

## What Layer 1 buys

A lint finding is CONFIRMED by `precheck()`'s `source == "lint"` branch before the `ruff:` branch
is ever reached - so it keeps its citation, costs no model call, and blocks when its severity says
it should. A hardcoded secret now blocks the merge at CRITICAL with zero model calls and a
citation that can be re-derived by re-running a command. `test_lint_layer.py` demonstrates this end
to end with the model stubbed to raise if it is ever called.

## Dismissal and severity

A dismissal records the severity it was made at (`dismissed_at_severity`). If a later push judges
the same code *more* severely than what was waived, the finding resurfaces rather than staying
suppressed — severity is deliberately not part of a fingerprint, so without this rule waving off a
style nit would go on suppressing the same lines after they turned out to leak a credential.
