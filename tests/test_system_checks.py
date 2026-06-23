from django.core import checks


def test_foundation_system_checks_pass_in_test_settings() -> None:
    errors = checks.run_checks()
    assert errors == []

