from django.db import migrations


HISTORICAL_MAJOR_ATOMIC_CODE = "structure_historical_major_zone_valid"


def forwards(apps, schema_editor):
    from apps.strategy_analysis.definition_hashes import domain_signal_definition_hash

    DomainSignalDefinition = apps.get_model("strategy_analysis", "DomainSignalDefinition")
    StrategyAnalysisWorkspaceItem = apps.get_model("strategy_analysis", "StrategyAnalysisWorkspaceItem")

    candidates = DomainSignalDefinition.objects.filter(
        domain_code="structure",
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
    )

    for definition in candidates:
        allowed_codes = list(definition.allowed_atomic_signal_codes or [])
        if HISTORICAL_MAJOR_ATOMIC_CODE not in allowed_codes:
            continue

        new_hash = domain_signal_definition_hash(
            domain_code=definition.domain_code,
            output_mode=definition.output_mode,
            algorithm_name=definition.algorithm_name,
            algorithm_version="1.1.0",
            params_hash=definition.params_hash,
            is_required=definition.is_required,
            allowed_atomic_signal_codes=definition.allowed_atomic_signal_codes,
            required_atomic_signal_codes=definition.required_atomic_signal_codes,
            minimum_coverage_ratio=definition.minimum_coverage_ratio,
            agreement_threshold=definition.agreement_threshold,
        )

        DomainSignalDefinition.objects.filter(id=definition.id).update(
            algorithm_version="1.1.0",
            definition_hash=new_hash,
        )

        StrategyAnalysisWorkspaceItem.objects.filter(
            component_type="domain_signal_definition",
            component_object_id=definition.id,
        ).update(
            component_version="1.1.0",
            definition_hash=new_hash,
        )


def backwards(apps, schema_editor):
    from apps.strategy_analysis.definition_hashes import domain_signal_definition_hash

    DomainSignalDefinition = apps.get_model("strategy_analysis", "DomainSignalDefinition")
    StrategyAnalysisWorkspaceItem = apps.get_model("strategy_analysis", "StrategyAnalysisWorkspaceItem")

    candidates = DomainSignalDefinition.objects.filter(
        domain_code="structure",
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.1.0",
    )

    for definition in candidates:
        allowed_codes = list(definition.allowed_atomic_signal_codes or [])
        if HISTORICAL_MAJOR_ATOMIC_CODE not in allowed_codes:
            continue

        old_hash = domain_signal_definition_hash(
            domain_code=definition.domain_code,
            output_mode=definition.output_mode,
            algorithm_name=definition.algorithm_name,
            algorithm_version="1.0.0",
            params_hash=definition.params_hash,
            is_required=definition.is_required,
            allowed_atomic_signal_codes=definition.allowed_atomic_signal_codes,
            required_atomic_signal_codes=definition.required_atomic_signal_codes,
            minimum_coverage_ratio=definition.minimum_coverage_ratio,
            agreement_threshold=definition.agreement_threshold,
        )

        DomainSignalDefinition.objects.filter(id=definition.id).update(
            algorithm_version="1.0.0",
            definition_hash=old_hash,
        )

        StrategyAnalysisWorkspaceItem.objects.filter(
            component_type="domain_signal_definition",
            component_object_id=definition.id,
        ).update(
            component_version="1.0.0",
            definition_hash=old_hash,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("strategy_analysis", "0019_strategy_route_rule_display_names"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
