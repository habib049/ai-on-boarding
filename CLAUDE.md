# ai-on-boarding

This repository demonstrates spec-driven development: a Django REST API (signup, signin) built
from written specifications rather than hand-written code. The actual project lives in
`sdd_django_demo/` — see `sdd_django_demo/CLAUDE.md` for its specific conventions, and
`sdd_django_demo/README.md` for the concrete process each feature went through.

Spec-driven development here is run through [OpenSpec](https://github.com/Fission-AI/OpenSpec):
`/opsx:propose`, `/opsx:apply`, `/opsx:archive`.

## Layout

- `sdd_django_demo/` — the Django + DRF project. Source of truth for what's actually built.
- `openspec/specs/<capability>/spec.md` — the current, canonical spec for each shipped
  capability (e.g. `openspec/specs/user-signup/spec.md`).
- `openspec/changes/<change-name>/` — an active, in-progress change: `proposal.md` (why/what),
  `specs/<capability>/spec.md` (the delta), `design.md` (how), `tasks.md` (checklist). Archived
  once implemented via `openspec archive`.
- `openspec/changes/archive/<date>-<change-name>/` — completed changes, kept as a historical
  record.
- `openspec/config.yaml` — this project's governing conventions: tech stack context, per-artifact
  rules (proposal/specs/design/tasks), and per-operation guidance (apply/archive). Read before
  proposing, implementing, or reviewing anything, in any directory. This is the OpenSpec
  equivalent of what used to be `.specify/memory/constitution.md`.
- `reference/`, `glossary.md` — supporting material for readers of this repo.
- `facilitator` branch — teaching material (guide, review checklists, conformance suite), kept
  separate from this branch.

## Read before implementing or reviewing anything

`openspec/config.yaml` governs this repository — its `context`, `rules`, and `operations`
sections apply to every change, in every directory. The part most relevant to code review,
inlined here so it's never missed — **the review contract** (from `operations.apply.guidance`):

- A finding blocks merge only if it cites a requirement (a `### Requirement:` from a spec), a
  specific named failing test, or a documented convention (`openspec/config.yaml`, this file, or
  `AGENTS.md`). Anything else is a nit: recorded, never blocking.
- Review runs at most two passes on a given piece of work: an initial pass, and one follow-up
  after fixes. The follow-up checks only what the first pass raised, plus anything the fixes
  broke — it does not go hunting for new material.
- Every review ends with an explicit verdict: `Ready to merge: yes` or `Ready to merge: no`,
  never an open-ended list with no conclusion. A `no` verdict enumerates every blocking finding
  by its citation. A `yes` verdict is a legitimate outcome, not evidence of insufficient effort.
- Only archive a change once `/code-review` has returned `Ready to merge: yes` for it, and
  `pytest` passes for the whole project.

Other conventions worth knowing up front (also in `openspec/config.yaml`):

- Tests are written after implementation, from the spec — not TDD. `tasks.md` is never generated
  with test-writing tasks; tests are a separate step after `/opsx:apply` finishes the
  implementation tasks.
- Security-sensitive behaviour (auth, credential storage, credential exposure) needs a test that
  asserts it directly, not incidentally through a success path.
- Credentials never appear as literals in tracked files. API keys, tokens, signing secrets, and
  passwords are read from the environment or Django settings, the way `SECRET_KEY` and
  `DATABASE_URL` already are — never written into source, fixtures, or config that git tracks. A
  secret committed to a tracked file is exposed from that commit onward whether or not the code
  using it ever runs, so unreachable or not-yet-wired code is no exception, and the fix is to
  rotate the secret, not only to delete the line.
- Code is generated from instructions (proposal, spec, design, tasks); when generated code is
  wrong, fix the instruction and regenerate rather than hand-patching the output.
- Requirement identifiers/names are permanent — a changed requirement keeps its identity, a
  removed one is marked `REMOVED` with a reason, never silently deleted or renumbered.
- Tasks are tracked in each change's `tasks.md` (checkbox state), and the corresponding GitHub
  issue mirrors that checklist for human visibility — not a separate source of truth.
