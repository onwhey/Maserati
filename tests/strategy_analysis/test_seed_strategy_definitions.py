from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.strategy_analysis.default_strategy_definitions import DEFAULT_STRATEGY_DEFINITIONS, REQUIRED_STRATEGY_DOMAIN_CODES
from apps.strategy_analysis.definition_hashes import normalize_domain_codes, strategy_definition_hash
from apps.strategy_analysis.models import DefinitionLifecycleStatus, StrategyDefinition
from apps.strategy_calculator.utils import stable_hash


@pytest.mark.django_db
def test_seed_strategy_definitions_creates_p0_strategy_definitions() -> None:
    out = StringIO()

    call_command("seed_strategy_definitions", stdout=out)

    assert "StrategyDefinition seed completed" in out.getvalue()
    assert StrategyDefinition.objects.count() == len(DEFAULT_STRATEGY_DEFINITIONS)
    definition = StrategyDefinition.objects.get(strategy_code="long_trend_following", strategy_version="v1")
    template = next(item for item in DEFAULT_STRATEGY_DEFINITIONS if item.strategy_code == "long_trend_following")
    assert definition.status == DefinitionLifecycleStatus.ACTIVE
    assert definition.enabled is True
    assert definition.algorithm_name == "long_trend_following"
    assert definition.algorithm_version == "v1"
    assert tuple(definition.allowed_domain_codes) == normalize_domain_codes(REQUIRED_STRATEGY_DOMAIN_CODES)
    assert tuple(definition.required_domain_codes) == normalize_domain_codes(REQUIRED_STRATEGY_DOMAIN_CODES)
    assert definition.prediction_horizon == "next_1_to_3_closed_4h"
    assert definition.definition_hash == strategy_definition_hash(
        strategy_code=definition.strategy_code,
        strategy_version=definition.strategy_version,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        params_hash=stable_hash(template.params),
        allowed_domain_codes=normalize_domain_codes(template.allowed_domain_codes),
        required_domain_codes=normalize_domain_codes(template.required_domain_codes),
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon=template.prediction_horizon,
    )


@pytest.mark.django_db
def test_seed_strategy_definitions_is_idempotent() -> None:
    call_command("seed_strategy_definitions", stdout=StringIO())
    first_ids = set(StrategyDefinition.objects.values_list("id", flat=True))

    call_command("seed_strategy_definitions", stdout=StringIO())

    assert set(StrategyDefinition.objects.values_list("id", flat=True)) == first_ids
    assert StrategyDefinition.objects.count() == len(DEFAULT_STRATEGY_DEFINITIONS)


@pytest.mark.django_db
def test_seed_strategy_definitions_does_not_restore_disabled_definition() -> None:
    call_command("seed_strategy_definitions", stdout=StringIO())
    StrategyDefinition.objects.filter(strategy_code="long_trend_following").update(
        status=DefinitionLifecycleStatus.DISABLED,
        enabled=False,
    )

    call_command("seed_strategy_definitions", stdout=StringIO())

    definition = StrategyDefinition.objects.get(strategy_code="long_trend_following", strategy_version="v1")
    assert definition.status == DefinitionLifecycleStatus.DISABLED
    assert definition.enabled is False


@pytest.mark.django_db
def test_seed_strategy_definitions_rejects_identity_conflict() -> None:
    StrategyDefinition.objects.create(
        strategy_code="long_trend_following",
        strategy_version="v1",
        algorithm_name="wrong_algorithm",
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={},
        params_hash=stable_hash({}),
        definition_hash=stable_hash({"conflict": True}),
        allowed_domain_codes=["trend"],
        required_domain_codes=["trend"],
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon="next_1_to_3_closed_4h",
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )

    with pytest.raises(CommandError, match="StrategyDefinition"):
        call_command("seed_strategy_definitions", stdout=StringIO())
