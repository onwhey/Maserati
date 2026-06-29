from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.strategy_analysis.default_definitions import DEFAULT_FEATURE_DEFINITIONS
from apps.strategy_analysis.definition_hashes import feature_definition_hash
from apps.strategy_analysis.models import FeatureDefinition
from apps.strategy_calculator.utils import stable_hash


@pytest.mark.django_db
def test_seed_feature_definitions_creates_default_templates() -> None:
    out = StringIO()

    call_command("seed_feature_definitions", stdout=out)

    assert FeatureDefinition.objects.count() == len(DEFAULT_FEATURE_DEFINITIONS)
    assert "FeatureDefinition seed completed" in out.getvalue()

    definition = FeatureDefinition.objects.get(feature_code="sma_4h_20", definition_version="1.0.0")
    assert definition.algorithm_name == "kline_price_features"
    assert definition.algorithm_version == "1.0.0"
    assert definition.params == {"operation": "sma", "timeframe": "4h", "window": 20}
    assert definition.params_hash == stable_hash(definition.params)
    assert definition.definition_hash == feature_definition_hash(
        feature_code=definition.feature_code,
        definition_version=definition.definition_version,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        params_hash=definition.params_hash,
        value_type=definition.value_type,
        input_timeframes=definition.input_timeframes,
        output_schema_version=definition.output_schema_version,
    )
    assert FeatureDefinition.objects.filter(feature_code="higher_high_count_1d_60_block20").exists()
    assert FeatureDefinition.objects.filter(feature_code="structure_minor_support_lower_4h_120").exists()
    assert FeatureDefinition.objects.filter(feature_code="latest_volume_4h").exists()
    structure_definition = FeatureDefinition.objects.get(feature_code="structure_minor_support_lower_4h_120")
    assert structure_definition.params["nullable"] is True


@pytest.mark.django_db
def test_seed_feature_definitions_is_idempotent() -> None:
    call_command("seed_feature_definitions", stdout=StringIO())
    first_ids = set(FeatureDefinition.objects.values_list("id", flat=True))

    call_command("seed_feature_definitions", stdout=StringIO())

    assert FeatureDefinition.objects.count() == len(DEFAULT_FEATURE_DEFINITIONS)
    assert set(FeatureDefinition.objects.values_list("id", flat=True)) == first_ids


@pytest.mark.django_db
def test_seed_feature_definitions_does_not_restore_disabled_definition() -> None:
    call_command("seed_feature_definitions", stdout=StringIO())
    FeatureDefinition.objects.filter(feature_code="sma_4h_20").update(is_enabled=False)

    call_command("seed_feature_definitions", stdout=StringIO())

    definition = FeatureDefinition.objects.get(feature_code="sma_4h_20")
    assert definition.is_enabled is False


@pytest.mark.django_db
def test_seed_feature_definitions_rejects_identity_conflict() -> None:
    FeatureDefinition.objects.create(
        feature_code="latest_close_1d",
        definition_version="1.0.0",
        display_name="conflict",
        description="conflict",
        definition_hash=stable_hash({"conflict": True}),
        algorithm_name="wrong_algorithm",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        value_type="decimal",
        input_timeframes=["1d"],
        output_schema_version="1.0",
    )

    with pytest.raises(CommandError, match="身份冲突"):
        call_command("seed_feature_definitions", stdout=StringIO())
