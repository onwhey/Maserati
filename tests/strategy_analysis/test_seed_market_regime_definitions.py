from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.strategy_analysis.default_market_regime_definitions import DEFAULT_MARKET_REGIME_DEFINITIONS
from apps.strategy_analysis.models import DefinitionLifecycleStatus, MarketRegimeDefinition
from apps.strategy_analysis.definition_hashes import normalize_domain_codes, normalize_regime_codes
from apps.strategy_calculator.market_regime.context_structure_regime import REGIME_CODES, REQUIRED_DOMAIN_CODES


@pytest.mark.django_db
def test_seed_market_regime_definitions_creates_default_definition() -> None:
    call_command("seed_market_regime_definitions")

    definition = MarketRegimeDefinition.objects.get(definition_code="context_structure_regime_v1")
    template = DEFAULT_MARKET_REGIME_DEFINITIONS[0]
    assert definition.status == DefinitionLifecycleStatus.ACTIVE
    assert definition.enabled is True
    assert definition.algorithm_name == template.algorithm_name
    assert definition.algorithm_version == template.algorithm_version
    assert tuple(definition.allowed_domain_codes) == normalize_domain_codes(REQUIRED_DOMAIN_CODES)
    assert tuple(definition.required_domain_codes) == normalize_domain_codes(REQUIRED_DOMAIN_CODES)
    assert tuple(definition.allowed_regime_codes) == normalize_regime_codes(REGIME_CODES)


@pytest.mark.django_db
def test_seed_market_regime_definitions_is_idempotent() -> None:
    call_command("seed_market_regime_definitions")
    call_command("seed_market_regime_definitions")

    assert MarketRegimeDefinition.objects.count() == 1
