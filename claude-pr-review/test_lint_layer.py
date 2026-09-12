"""What Layer 1 is actually worth: real ruff runs through the whole
pipeline, with the model stubbed to explode if it's ever called.

These exist because "we reject all the ruff findings anyway, so what is the
lint layer for?" is a fair question to ask of the code, and the answer
should be demonstrable rather than argued. A lint finding is CONFIRMED by
citations.precheck()'s `source == "lint"` branch before the `ruff:` branch
is ever reached, so it keeps its citation, costs nothing, and blocks when
its severity says it should.
"""
from __future__ import annotations

from pathlib import Path

import citations
import gate
import judge
import lint
import severity
import target
import verify

PROBE = target.REPO_ROOT / "_lint_layer_probe.py"


class _Unreachable:
    def __getattr__(self, name):
        raise AssertionError("a model call was made for a lint-sourced finding")


class _Ctx:
    convention_text = ""
    test_index: set[str] = set()

    def lint_codes_near(self, *a, **k):
        return set()


def _pipeline(source: str):
    """Write a probe file, run Layer 1 -> 4 over it, clean up."""
    PROBE.write_text(source)
    try:
        findings = judge._lint_as_findings(lint.run([PROBE.name]))
        verified = verify.verify(_Unreachable(), diff="", rules={}, findings={"findings": findings})
        report, ready = gate.render(verified)
        return findings, verified["findings"], report, ready
    finally:
        PROBE.unlink(missing_ok=True)


def test_lint_findings_are_confirmed_not_rejected():
    findings, _, _, _ = _pipeline("import os\n")
    assert findings, "ruff should have flagged the unused import"
    for f in findings:
        assert citations.precheck(f, _Ctx()) is citations.Precheck.CONFIRMED


def test_lint_findings_keep_their_citations_through_layer_3():
    _, kept, _, _ = _pipeline("import os\n")
    assert kept
    assert all(f["citation"].startswith("ruff:") for f in kept)


def test_lint_findings_cost_no_model_calls():
    # _Unreachable raises if the client is touched at all; reaching the end
    # of the pipeline is the assertion.
    _, kept, _, _ = _pipeline("import os\n")
    assert kept


def test_a_hardcoded_secret_blocks_on_lint_alone():
    # The acid test. This is the scenario evals/fixtures/006 was built
    # around, and it used to require a paid Layer 2 call to catch at all.
    findings, kept, report, ready = _pipeline(
        'API_SIGNING_SECRET = "sk-hardcoded-super-secret-do-not-commit-123"\n'
    )
    assert any(f["citation"] == "ruff:S105" for f in findings)
    assert any(f["severity"] == "CRITICAL" for f in findings)
    assert ready is False
    assert "## Blocking" in report


def test_undefined_name_blocks_as_major():
    findings, _, _, ready = _pipeline("def f():\n    return not_defined_anywhere()\n")
    assert any(f["citation"] == "ruff:F821" and f["severity"] == "MAJOR" for f in findings)
    assert ready is False


def test_style_only_violations_do_not_block():
    # An unused import is a nit, not a merge blocker - the whole point of
    # the severity map replacing a blanket MAJOR.
    findings, _, report, ready = _pipeline("import os\n")
    assert all(f["severity"] == "MINOR" for f in findings)
    assert ready is True
    assert "## Nits" in report


def test_a_clean_file_produces_nothing():
    findings, kept, _, ready = _pipeline("def add(a, b):\n    return a + b\n")
    assert findings == []
    assert kept == []
    assert ready is True


# --- the severity map must stay reachable from the lint config ---

def _selected_prefixes() -> list[str]:
    text = (Path(__file__).resolve().parent / "ruff.toml").read_text()
    select_line = next(ln for ln in text.splitlines() if ln.startswith("select ="))
    return [p.strip(' "') for p in select_line.split("[", 1)[1].rstrip("]").split(",")]


def test_every_severity_map_prefix_is_actually_selected():
    # severity.py mapped S -> CRITICAL and B -> MAJOR while ruff.toml
    # selected only E/F/I, so those rows could never fire: the map promised
    # a security tier the linter was never asked to check. Keep them in
    # sync, or the top of Layer 1's severity range is decoration.
    selected = _selected_prefixes()
    for prefix in severity.RUFF_SEVERITY:
        assert any(prefix.startswith(s) for s in selected), (
            f"severity.py maps {prefix!r} but ruff.toml never selects it"
        )


def test_security_rules_can_reach_critical():
    assert severity.severity_for_ruff("S105") == "CRITICAL"
    assert "S" in _selected_prefixes()


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
