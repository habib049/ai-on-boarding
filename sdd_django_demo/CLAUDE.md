# sdd_django_demo

This project follows spec-driven development via [OpenSpec](https://github.com/Fission-AI/OpenSpec).
Before implementing or reviewing anything here, read `../openspec/config.yaml` (repo root, one
level up) — its `context`, `rules`, and `operations` sections govern this project and are not
optional guidance.

The part most relevant to code review, inlined here so it is never missed even if that file
isn't separately opened — **the review contract**:

- A finding blocks merge only if it cites a requirement (a `### Requirement:` from a spec), a
  specific named failing test, or a documented convention (`openspec/config.yaml`, this file, or
  `AGENTS.md`). Anything else is a nit: recorded, never blocking.
- Review runs at most two passes on a given piece of work: an initial pass, and one follow-up
  after fixes. The follow-up checks only what the first pass raised, plus anything the fixes
  broke.
- Every review ends with an explicit verdict: `Ready to merge: yes` or `Ready to merge: no`,
  never an open-ended list with no conclusion. A `no` verdict enumerates every blocking finding
  by its citation.

Other conventions worth knowing before touching this code:

- Every behavioural requirement needs an automated test before it's considered satisfied;
  security-sensitive behaviour — auth, credential storage, credential exposure — needs tests
  that assert it directly, not incidentally.
- Credentials never appear as literals in tracked files. API keys, tokens, signing secrets, and
  passwords are read from the environment or Django settings, the way `SECRET_KEY` and
  `DATABASE_URL` already are — never written into source, fixtures, or config that git tracks. A
  secret committed to a tracked file is exposed from that commit onward whether or not the code
  using it ever runs, so unreachable or not-yet-wired code is no exception.
- Tests are written after implementation, from the spec — not TDD. `openspec instructions tasks`
  never generates test-writing tasks for this project.
- Code is generated from instructions (proposal, spec, design, tasks); when generated code is
  wrong, fix the instruction and regenerate rather than hand-patching the output.
- Requirement identifiers/names in `openspec/specs/*/spec.md` are permanent — a changed
  requirement keeps its identity, a removed one is marked `REMOVED` with a reason.

Current and past feature specs live in `../openspec/specs/` (canonical) and
`../openspec/changes/` (in-progress or archived). See `README.md` in this directory for the
concrete process each feature has gone through so far.
