"""Test table for severity.py, written before the implementation per the
Phase 1 plan. Run directly: pure, no API key, no network.
"""
from __future__ import annotations

import severity


def test_bandit_security_is_critical():
    assert severity.severity_for_ruff("S105") == "CRITICAL"


def test_undefined_name_is_major():
    assert severity.severity_for_ruff("F821") == "MAJOR"


def test_redefinition_is_major():
    assert severity.severity_for_ruff("F811") == "MAJOR"


def test_bugbear_is_major():
    assert severity.severity_for_ruff("B006") == "MAJOR"


def test_unused_import_is_minor():
    assert severity.severity_for_ruff("F401") == "MINOR"


def test_pycodestyle_error_is_minor():
    assert severity.severity_for_ruff("E501") == "MINOR"


def test_pycodestyle_warning_is_minor():
    assert severity.severity_for_ruff("W291") == "MINOR"


def test_import_sort_is_minor():
    assert severity.severity_for_ruff("I001") == "MINOR"


def test_naming_is_minor():
    assert severity.severity_for_ruff("N806") == "MINOR"


def test_longest_prefix_wins_f821_over_f():
    # F821 (undefined name, MAJOR) must not fall through to the generic F
    # (MINOR) bucket just because "F" is also a registered prefix.
    assert severity.severity_for_ruff("F821") != severity.severity_for_ruff("F401")


def test_longest_prefix_wins_f811_over_f():
    assert severity.severity_for_ruff("F811") != severity.severity_for_ruff("F401")


def test_unknown_prefix_defaults_to_minor():
    assert severity.severity_for_ruff("ZZZ999") == "MINOR"


def test_max_severity_critical_beats_everything():
    assert severity.max_severity("CRITICAL", "MINOR") == "CRITICAL"
    assert severity.max_severity("MINOR", "CRITICAL") == "CRITICAL"


def test_max_severity_major_beats_minor():
    assert severity.max_severity("MAJOR", "MINOR") == "MAJOR"


def test_max_severity_equal_is_stable():
    assert severity.max_severity("MAJOR", "MAJOR") == "MAJOR"


TESTS = [v for k, v in list(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"ok ({len(TESTS)} tests)")
