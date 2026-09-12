"""Tests for verify.py's 1.2 (citation precheck integration) and 1.5
(verifier fails closed). No API key, no network - the model client is
stubbed or never reached for the CONFIRMED/REJECTED paths.

Every finding verify.verify() returns now carries `l2_severity` (Phase 2's
severity-floor bookkeeping - see gate.py's _assert_severity_floor), so
these compare individual fields rather than the whole dict where that
extra key would otherwise make an equality check fail for the wrong reason.
"""
from __future__ import annotations

import agent
import verify


class _UnreachableClient:
    def __getattr__(self, name):
        raise AssertionError(f"client.{name} must not be reached for a deterministic precheck outcome")


def _finding(file="a.py", line=1, severity="MAJOR", citation="x", summary="s"):
    return {"file": file, "line": line, "severity": severity, "citation": citation, "summary": summary}


def test_confirmed_citation_skips_model_and_keeps_finding_unchanged():
    finding = _finding(citation='CLAUDE.md: "needs a test that asserts it directly"')
    rules = {"CLAUDE.md": "Security-sensitive behaviour needs a test that asserts it directly, not incidentally."}
    result = verify.verify(_UnreachableClient(), diff="", rules=rules, findings={"findings": [finding]})
    [out] = result["findings"]
    assert out["citation"] == finding["citation"]
    assert out["severity"] == finding["severity"]
    assert out["l2_severity"] == finding["severity"]


def test_rejected_citation_skips_model_and_strips_citation_only():
    finding = _finding(severity="CRITICAL", citation='CLAUDE.md: "this text is invented and does not exist"')
    rules = {"CLAUDE.md": "Something else entirely."}
    result = verify.verify(_UnreachableClient(), diff="", rules=rules, findings={"findings": [finding]})
    [out] = result["findings"]
    assert out["citation"] is None
    assert out["severity"] == "CRITICAL"  # severity is never touched by a rejected citation


def test_missing_citation_skips_model_and_stays_uncited():
    finding = _finding(citation=None)
    result = verify.verify(_UnreachableClient(), diff="", rules={}, findings={"findings": [finding]})
    [out] = result["findings"]
    assert out["citation"] is None


def test_needs_model_citation_calls_the_agent_without_severity():
    finding = _finding(citation="this looks wrong to me, no quote or test name")
    calls = []

    def fake_run(client, model, system, stable_content, variable_content="", **kwargs):
        calls.append(variable_content)
        return {"verified": True, "citation_holds": True, "escalate_to": None, "reasoning": "checked it"}

    original = agent.run
    verify.agent.run = fake_run
    try:
        result = verify.verify(object(), diff="d", rules={}, findings={"findings": [finding]})
    finally:
        verify.agent.run = original

    assert len(calls) == 1
    assert '"severity"' not in calls[0]  # 2.2: the verifier is never shown Layer 2's severity
    assert result["findings"][0]["citation"] == finding["citation"]


def test_verified_false_drops_the_finding():
    finding = _finding()

    def fake_run(client, model, system, stable_content, variable_content="", **kwargs):
        return {"verified": False, "citation_holds": False, "escalate_to": None, "reasoning": "doesn't hold up"}

    original = agent.run
    verify.agent.run = fake_run
    try:
        result = verify.verify(object(), diff="d", rules={}, findings={"findings": [finding]})
    finally:
        verify.agent.run = original

    assert result["findings"] == []


def test_escalate_to_raises_severity_but_never_lowers():
    finding = _finding(severity="MAJOR")

    def fake_run(client, model, system, stable_content, variable_content="", **kwargs):
        return {"verified": True, "citation_holds": True, "escalate_to": "CRITICAL", "reasoning": "worse than it looked"}

    original = agent.run
    verify.agent.run = fake_run
    try:
        result = verify.verify(object(), diff="d", rules={}, findings={"findings": [finding]})
    finally:
        verify.agent.run = original

    [out] = result["findings"]
    assert out["severity"] == "CRITICAL"
    assert out["l2_severity"] == "MAJOR"  # the floor gate.py checks against


def test_fails_closed_after_retries_preserves_severity_and_citation():
    finding = _finding(severity="CRITICAL", citation="this looks wrong to me, no quote or test name")

    def always_fails(client, model, system, stable_content, variable_content="", **kwargs):
        raise agent.AgentError("simulated transient failure")

    original_run, original_sleep = agent.run, verify.time.sleep
    verify.agent.run = always_fails
    verify.time.sleep = lambda *_: None  # don't actually wait through the backoff in tests
    try:
        result = verify.verify(object(), diff="d", rules={}, findings={"findings": [finding]})
    finally:
        verify.agent.run = original_run
        verify.time.sleep = original_sleep

    [out] = result["findings"]
    assert out["unverified"] is True
    assert out["severity"] == "CRITICAL"           # never downgraded
    assert out["citation"] == finding["citation"]  # never stripped by an infra failure


def test_critical_finding_routes_to_sonnet_others_to_haiku():
    models_used = []

    def fake_run(client, model, system, stable_content, variable_content="", **kwargs):
        models_used.append(model)
        return {"verified": True, "citation_holds": True, "escalate_to": None, "reasoning": "ok"}

    findings = {
        "findings": [
            _finding(file="a.py", severity="CRITICAL", citation="freeform, no quote or test name here"),
            _finding(file="b.py", severity="MAJOR", citation="freeform, no quote or test name here either"),
        ]
    }
    original = agent.run
    verify.agent.run = fake_run
    try:
        verify.verify(object(), diff="d", rules={}, findings=findings)
    finally:
        verify.agent.run = original

    assert models_used == [verify.MODEL_SONNET, verify.MODEL_HAIKU]


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
