from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.strategy_analysis.default_strategy_signal_quality_definitions import (
    DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS,
)
from apps.strategy_analysis.definition_hashes import strategy_signal_quality_rule_set_hash
from apps.strategy_analysis.models import DefinitionLifecycleStatus, StrategySignalQualityRuleSet
from apps.strategy_calculator.utils import stable_hash


@pytest.mark.django_db
def test_seed_strategy_signal_quality_rule_sets_creates_default_rule_set() -> None:
    out = StringIO()

    call_command("seed_strategy_signal_quality_rule_sets", stdout=out)

    assert "StrategySignalQualityRuleSet seed completed" in out.getvalue()
    assert StrategySignalQualityRuleSet.objects.count() == len(DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS)
    template = DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS[0]
    rule_set = StrategySignalQualityRuleSet.objects.get(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
    )
    assert rule_set.status == DefinitionLifecycleStatus.ACTIVE
    assert rule_set.enabled is True
    assert rule_set.display_name == template.display_name
    assert rule_set.max_staleness_seconds == 21600
    assert rule_set.warning_blocks_decision is False
    assert rule_set.fail_alert_enabled is True
    assert rule_set.warning_alert_enabled is False
    assert rule_set.params["p0_blocks_only_error_or_critical"] is True
    assert rule_set.params_hash == stable_hash(template.params)
    assert rule_set.rule_set_hash == strategy_signal_quality_rule_set_hash(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
        quality_schema_version=template.quality_schema_version,
        max_staleness_seconds=template.max_staleness_seconds,
        warning_blocks_decision=template.warning_blocks_decision,
        fail_alert_enabled=template.fail_alert_enabled,
        warning_alert_enabled=template.warning_alert_enabled,
        consecutive_failure_threshold=template.consecutive_failure_threshold,
        params_hash=stable_hash(template.params),
    )


@pytest.mark.django_db
def test_seed_strategy_signal_quality_rule_sets_is_idempotent() -> None:
    call_command("seed_strategy_signal_quality_rule_sets", stdout=StringIO())
    first_ids = set(StrategySignalQualityRuleSet.objects.values_list("id", flat=True))

    call_command("seed_strategy_signal_quality_rule_sets", stdout=StringIO())

    assert set(StrategySignalQualityRuleSet.objects.values_list("id", flat=True)) == first_ids
    assert StrategySignalQualityRuleSet.objects.count() == len(DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS)


@pytest.mark.django_db
def test_seed_strategy_signal_quality_rule_sets_does_not_restore_disabled_rule_set() -> None:
    call_command("seed_strategy_signal_quality_rule_sets", stdout=StringIO())
    template = DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS[0]
    StrategySignalQualityRuleSet.objects.filter(rule_set_code=template.rule_set_code).update(
        status=DefinitionLifecycleStatus.DISABLED,
        enabled=False,
    )

    call_command("seed_strategy_signal_quality_rule_sets", stdout=StringIO())

    rule_set = StrategySignalQualityRuleSet.objects.get(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
    )
    assert rule_set.status == DefinitionLifecycleStatus.DISABLED
    assert rule_set.enabled is False


@pytest.mark.django_db
def test_seed_strategy_signal_quality_rule_sets_rejects_identity_conflict() -> None:
    template = DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS[0]
    StrategySignalQualityRuleSet.objects.create(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
        quality_schema_version="wrong",
        max_staleness_seconds=0,
        warning_blocks_decision=True,
        fail_alert_enabled=False,
        warning_alert_enabled=True,
        consecutive_failure_threshold=1,
        params={},
        params_hash=stable_hash({}),
        rule_set_hash=stable_hash({"conflict": True}),
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )

    with pytest.raises(CommandError, match="StrategySignalQualityRuleSet"):
        call_command("seed_strategy_signal_quality_rule_sets", stdout=StringIO())
