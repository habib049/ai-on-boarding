# Spec-Driven Development

A user signup and signin API, built without writing the code by hand.

That sentence is the whole point. Each feature starts as a written **specification** — a precise
description of how it must behave — and an AI coding agent turns it into Django code. The job is
to decide what the software should do, to say it precisely enough that it can be built and
tested, and to verify that what came back actually matches what was asked for.

This is called **spec-driven development**. The specification is the source of truth. Code
exists to satisfy it, and tests are the executable evidence that it does. The actual build —
`sdd_django_demo/` — documents this process end to end for both features in
[`sdd_django_demo/README.md`](sdd_django_demo/README.md).

## What actually happens

This project runs spec-driven development through [OpenSpec](https://github.com/Fission-AI/OpenSpec).
A feature moves from idea to reviewed, tested code as a **change**, living in
`openspec/changes/<name>/` until it's implemented, then archived.

| You run | It produces | You then |
|---|---|---|
| `/opsx:propose "<idea>"` | a new `openspec/changes/<name>/` with `proposal.md` (why/what), a delta `specs/<capability>/spec.md` (requirements), `design.md` (how), `tasks.md` (checklist) — all generated together | Read every line and hunt for invented detail |
| — | a GitHub issue for the change (created if none exists), with the proposal and full delta spec posted as comments — `openspec/config.yaml`'s `rules.tasks` requires this once all four artifacts are complete | Read the issue on its own — it should need no repo access to understand what's being built |
| — | *your review of the proposal* | Fix ambiguity in the proposal/spec, not later in the code |
| `/opsx:apply` | working Django code, one `tasks.md` item at a time, checked off `[x]` as it lands | Then write tests **from the spec**, not from the code |
| — | `traceability.md` | Map every requirement to its code and test by hand — nothing generates this link for you |
| `/code-review` | findings bound by the review contract in `openspec/config.yaml` / `CLAUDE.md`, ending in an explicit verdict | Fix what's blocking, re-run for a second (and final) pass, then open a pull request |
| `/opsx:archive` | moves the change to `openspec/changes/archive/`, merges its delta spec into the canonical `openspec/specs/<capability>/spec.md` | Only after `Ready to merge: yes` and `pytest` passes for the whole project — this is a config-enforced rule, not a habit |

`tasks.md`'s checkbox state — not a separate GitHub-issue checklist — is where task status
lives; `tasks.md` in the change folder is the thing `/opsx:apply` actually reads and updates. The
GitHub issue mirrors it for human visibility, and carries more than just tasks: the proposal and
full delta spec get posted there too, so the issue is readable on its own without cloning the
repo — see issues [#9](https://github.com/awais786/ai-on-boarding/issues/9) and
[#10](https://github.com/awais786/ai-on-boarding/issues/10) for what that looks like in practice.

`/code-review` is not optional theatre and it is not open-ended. `CLAUDE.md`/`AGENTS.md` (root
and `sdd_django_demo/`) point it at the review contract in `openspec/config.yaml`: a finding
blocks only if it cites a requirement, a named failing test, or a documented convention; it runs
at most two passes — an initial pass and one follow-up after fixes, never a third; and it always
ends with `Ready to merge: yes` or `Ready to merge: no`, stated plainly, never left as an open
list. That last part is what stops review from becoming the thing that never converges — see the
signup build in `sdd_django_demo/README.md` for a real example of both passes.

The chain is the thing to watch:

```
requirement "Enforce a minimum password strength"  →  tasks.md item  →  api/serializers.py:18  →  test_signup_rejects_password_shorter_than_minimum
```

If any link is missing, something is wrong: a requirement with no test is unverified behaviour, a
test with no requirement is work nobody asked for, and a requirement with no code was never
built at all.

**Tests come after the implementation, deliberately.** This is not test-driven development. You
write tests from the specification once the code exists, which is harder than it sounds — the
temptation is to read the code and describe what it already does, and a test written that way
can never fail.

## What you will learn

Not Django. Django is the material, not the subject.

- **To write a requirement that can be tested.** *"Passwords should be secure"* cannot be. *"Passwords shorter than 8 characters are rejected with a 400 and a field-level error"* can. Telling those apart, reliably, is the core skill.
- **To spot what an agent invented.** Ask for three fields and you will get status codes, token strategies and validation rules you never mentioned. Some will be right. Deciding which is your job, and it is the job that does not go away.
- **To fix the instruction, not the output.** When generated code is nearly right, patching it by hand is faster and leaves the instruction still wrong. The next regeneration brings the bug back.
- **To change a finished feature properly.** A request arrives after signup is built and merged. You will edit the specification first and let the change propagate — spec, plan, tasks, tests, code — rather than reaching straight for the view.
- **To tell three kinds of wrong apart.** A code bug means the code disagrees with the spec. A spec bug means the spec says the wrong thing. A gap means nobody ever decided. Each has a different fix, and confusing them is how teams argue for a week.
- **To end a code review.** Reviews that never converge are reviews with no agreed standard. You will work under a contract where findings must cite a requirement, a failing test or a documented convention — and where `PASS` is an expected outcome, not a failure of diligence.

## The house rule

**You do not hand-write code.** Not the models, not the views, not the tests.

You write and edit *instructions* — the proposal, the spec, `openspec/config.yaml`'s project
conventions, and `CLAUDE.md`/`AGENTS.md` describing how this project does Django. The agent
turns those into code. That division is the whole point: humans own intent, agents own
implementation.

You will be tempted to break this, usually when something is nearly right and a two-line edit
would finish it. When you feel that, stop and ask a better question: **which instruction failed
to produce this?** Hand-editing the code fixes one symptom and leaves the instruction wrong, so
the next regeneration reintroduces the problem. Fix the instruction instead.

If you do end up editing code by hand — and occasionally you will — treat it as a finding worth
writing down, not a shortcut worth repeating.

## Who this is for

Developers who are new to Django, new to AI-assisted development, or both. Knowing Django,
Django REST Framework, or pytest going in isn't required — this project is set up so Django is
never the subject, it's the material spec-driven development is practised on.

**You do need:**

- Python 3.12 or newer installed (`python3 --version`) — Django 6.1's own floor; the project was
  built and tested on 3.14, but nothing in it depends on that specific version
- Git, and a GitHub account
- A terminal you are comfortable opening
- [Claude Code](https://docs.claude.com/en/docs/claude-code) installed
- [Pylint](https://pylint.readthedocs.io/) installed and on your `PATH` (e.g. `brew install pylint`
  or `pipx install pylint`) — `.claude/hooks/pylint-check.py` runs it after every Python file edit
  and feeds findings back to the agent; without it, that hook silently skips
- **A lead** — someone who reviews the pull request before it merges. Working alone, a fresh
  Claude Code session can stand in, though it will not push back on a product decision the way a
  person will.

## What this repository contains

- A working Django REST API with a tested, reviewed signup endpoint — signin is specced and
  planned but not yet implemented; see *Status* in `sdd_django_demo/README.md` for exactly where
  each feature stands right now
- Interactive Swagger docs for it, usable to verify the API by hand and to check the generated
  schema against the specification
- A specification for each feature, precise enough to rebuild it from scratch
- A traceability table linking every requirement to the code and the test that satisfies it
- Evidence a reviewer can check against — including proof that at least one test per feature can
  actually fail
- A worked example of a feature request landing on a finished feature, propagated from the
  specification outward rather than patched into the code

See [`sdd_django_demo/README.md`](sdd_django_demo/README.md) for the concrete process each
feature went through, spec to code, and current status.

## The reading behind it

[`glossary.md`](glossary.md) defines every artefact — constitution, skill, specification, plan,
task, verification — in one place, along with the distinctions people most often blur. Skim it
now, and come back whenever a word stops making sense.

Facilitator material — a teaching guide, change requests, review checklists and a conformance
suite — lives on the `facilitator` branch.
