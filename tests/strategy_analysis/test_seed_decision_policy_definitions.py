from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.strategy_analysis.default_decision_policy_definitions import DEFAULT_DECISION_POLICY_DEFINITIONS
from apps.strategy_analysis.definition_hashes import decision_policy_definition_hash
from apps.strategy_analysis.models import DecisionPolicyDefinition, DefinitionLifecycleStatus
from apps.strategy_calculator.utils import stable_hash


@pytest.mark.django_db
def test_seed_decision_policy_definitions_creates_position_policy_definition() -> None:
    out = StringIO()

    call_command("seed_decision_policy_definitions", stdout=out)

    assert "DecisionPolicyDefinition seed completed" in out.getvalue()
    assert DecisionPolicyDefinition.objects.count() == len(DEFAULT_DECISION_POLICY_DEFINITIONS)
    definition = DecisionPolicyDefinition.objects.get(policy_code="position_policy", policy_version="v1")
    template = DEFAULT_DECISION_POLICY_DEFINITIONS[0]
    assert definition.status == DefinitionLifecycleStatus.ACTIVE
    assert definition.enabled is True
    assert definition.algorithm_name == "position_policy"
    assert definition.algorithm_version == "v1"
    assert definition.params["expires_after_seconds"] == 14400
    assert definition.definition_hash == decision_policy_definition_hash(
        policy_code=definition.policy_code,
        policy_version=definition.policy_version,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        target_schema_version=definition.target_schema_version,
        params_hash=stable_hash(template.params),
    )


@pytest.mark.django_db
def test_seed_decision_policy_definitions_is_idempotent() -> None:
    call_command("seed_decision_policy_definitions", stdout=StringIO())
    first_ids = set(DecisionPolicyDefinition.objects.values_list("id", flat=True))

    call_command("seed_decision_policy_definitions", stdout=StringIO())

    assert set(DecisionPolicyDefinition.objects.values_list("id", flat=True)) == first_ids
    assert DecisionPolicyDefinition.objects.count() == len(DEFAULT_DECISION_POLICY_DEFINITIONS)


@pytest.mark.django_db
def test_seed_decision_policy_definitions_does_not_restore_disabled_definition() -> None:
    call_command("seed_decision_policy_definitions", stdout=StringIO())
    DecisionPolicyDefinition.objects.filter(policy_code="position_policy").update(
        status=DefinitionLifecycleStatus.DISABLED,
        enabled=False,
    )

    call_command("seed_decision_policy_definitions", stdout=StringIO())

    definition = DecisionPolicyDefinition.objects.get(policy_code="position_policy", policy_version="v1")
    assert definition.status == DefinitionLifecycleStatus.DISABLED
    assert definition.enabled is False


@pytest.mark.django_db
def test_seed_decision_policy_definitions_rejects_identity_conflict() -> None:
    DecisionPolicyDefinition.objects.create(
        policy_code="position_policy",
        policy_version="v1",
        algorithm_name="wrong_algorithm",
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        target_schema_version="1.0",
        params={},
        params_hash=stable_hash({}),
        definition_hash=stable_hash({"conflict": True}),
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )

    with pytest.raises(CommandError, match="DecisionPolicyDefinition"):
        call_command("seed_decision_policy_definitions", stdout=StringIO())
