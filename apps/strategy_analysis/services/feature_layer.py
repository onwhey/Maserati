"""StrategyAnalysis 模块：实现 FeatureLayer 正式 service；读写数据库，不访问 Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult
from apps.market_data.domain import TIMEFRAME_1D, TIMEFRAME_4H, configured_collection_domain, expected_open_times
from apps.market_data.models import CommonStatus, Kline, MarketSnapshot
from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorOutput, CalculatorType
from apps.strategy_calculator.errors import InvalidCalculatorContractError, StrategyCalculatorError
from apps.strategy_calculator.registry import CalculatorRegistry, default_registry
from apps.strategy_calculator.utils import stable_hash, thaw_value

from ..models import AnalysisObjectStatus, FeatureDefinition, FeatureSet, FeatureValue, FeatureValueType, ReleaseItemComponentType
from .release import resolve_frozen_slice


def _json_ready(value: Any) -> Any:
    value = thaw_value(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def _record_block_alert(
    *,
    event_key: str,
    title_zh: str,
    message_zh: str,
    reason_code: str,
    trace_id: str,
    trigger_source: str,
    payload_summary: dict[str, Any] | None = None,
) -> None:
    record_alert_event(
        event_key=event_key,
        source_module="FeatureLayer",
        event_type="feature_layer_blocked",
        event_category="strategy_analysis",
        severity=AlertSeverity.WARNING,
        title_zh=title_zh,
        message_zh=message_zh,
        trace_id=trace_id,
        trigger_source=trigger_source,
        business_status=AnalysisObjectStatus.BLOCKED,
        reason_code=reason_code,
        payload_summary=payload_summary or {},
    )


def _problem_result(
    *,
    status: ResultStatus,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    if not dry_run:
        if status == ResultStatus.BLOCKED:
            event_type = "feature_layer_blocked"
            business_status = AnalysisObjectStatus.BLOCKED
            severity = AlertSeverity.WARNING
        elif status == ResultStatus.UNKNOWN:
            event_type = "feature_set_unknown"
            business_status = AnalysisObjectStatus.UNKNOWN
            severity = AlertSeverity.HIGH
        else:
            event_type = "feature_set_failed"
            business_status = AnalysisObjectStatus.FAILED
            severity = AlertSeverity.HIGH
        record_alert_event(
            event_key=build_idempotency_key(event_type, business_request_key, reason_code),
            source_module="FeatureLayer",
            event_type=event_type,
            event_category="strategy_analysis",
            severity=severity,
            title_zh=f"FeatureLayer {'阻断' if status == ResultStatus.BLOCKED else '失败'}：{reason_code}",
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status=business_status,
            reason_code=reason_code,
            payload_summary=payload_summary or {},
        )
    return ServiceResult(status, reason_code, message, trace_id, trigger_source)


def _market_snapshot_input(snapshot: MarketSnapshot) -> tuple[dict[str, Any] | None, str]:
    domain = configured_collection_domain()
    if (
        snapshot.exchange != domain.exchange
        or snapshot.market_type != domain.market_type
        or snapshot.symbol != domain.symbol
        or snapshot.base_timeframe != TIMEFRAME_4H
        or snapshot.higher_timeframe != TIMEFRAME_1D
        or set(domain.timeframes) != {TIMEFRAME_4H, TIMEFRAME_1D}
    ):
        return None, "market_snapshot_domain_mismatch"

    klines_4h = list(Kline.objects.filter(
        exchange=snapshot.exchange,
        market_type=snapshot.market_type,
        symbol=snapshot.symbol,
        timeframe=snapshot.base_timeframe,
        open_time_utc__gte=snapshot.start_4h_open_time_utc,
        open_time_utc__lte=snapshot.end_4h_open_time_utc,
    ).order_by("open_time_utc"))
    klines_1d = list(Kline.objects.filter(
        exchange=snapshot.exchange,
        market_type=snapshot.market_type,
        symbol=snapshot.symbol,
        timeframe=snapshot.higher_timeframe,
        open_time_utc__gte=snapshot.start_1d_open_time_utc,
        open_time_utc__lte=snapshot.end_1d_open_time_utc,
    ).order_by("open_time_utc"))

    window_checks = (
        (TIMEFRAME_4H, klines_4h, snapshot.start_4h_open_time_utc, snapshot.end_4h_open_time_utc, snapshot.lookback_4h_count, snapshot.actual_4h_count, snapshot.latest_4h_open_time_utc),
        (TIMEFRAME_1D, klines_1d, snapshot.start_1d_open_time_utc, snapshot.end_1d_open_time_utc, snapshot.lookback_1d_count, snapshot.actual_1d_count, snapshot.latest_1d_open_time_utc),
    )
    for timeframe, klines, start_open, end_open, lookback_count, actual_count, latest_open in window_checks:
        expected = expected_open_times(start_open, end_open, timeframe)
        actual = [kline.open_time_utc for kline in klines]
        if actual_count != lookback_count or len(klines) != lookback_count:
            return None, f"{timeframe}_kline_count_mismatch"
        if actual != expected or latest_open != end_open:
            return None, f"{timeframe}_kline_window_mismatch"
        if any(kline.close_time_utc >= snapshot.analysis_reference_time_utc for kline in klines):
            return None, f"{timeframe}_kline_unclosed"

    return {
        "analysis_close_time_utc": snapshot.analysis_close_time_utc.isoformat(),
        TIMEFRAME_4H: [_kline_summary(kline) for kline in klines_4h],
        TIMEFRAME_1D: [_kline_summary(kline) for kline in klines_1d],
    }, ""


def _kline_summary(kline: Kline) -> dict[str, str]:
    return {
        "open_time_utc": kline.open_time_utc.isoformat(),
        "close_time_utc": kline.close_time_utc.isoformat(),
        "open": str(kline.open_price),
        "high": str(kline.high_price),
        "low": str(kline.low_price),
        "close": str(kline.close_price),
        "volume": str(kline.volume),
    }


def _extract_feature_value(definition: FeatureDefinition, output: CalculatorOutput) -> dict[str, Any]:
    value = thaw_value(output.values).get("value")
    if definition.value_type == FeatureValueType.DECIMAL:
        if value is None and bool((definition.params or {}).get("nullable")):
            return {"numeric_value": None, "bool_value": None, "text_value": ""}
        try:
            decimal_value = Decimal(str(value))
            if not decimal_value.is_finite():
                raise InvalidCalculatorContractError(f"{definition.feature_code} 输出不是有限 Decimal")
            return {"numeric_value": decimal_value, "bool_value": None, "text_value": ""}
        except (InvalidOperation, TypeError) as exc:
            raise InvalidCalculatorContractError(f"{definition.feature_code} 输出不是合法 Decimal") from exc
    if definition.value_type == FeatureValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise InvalidCalculatorContractError(f"{definition.feature_code} 输出不是合法 bool")
        return {"numeric_value": None, "bool_value": value, "text_value": ""}
    if definition.value_type == FeatureValueType.TEXT:
        text_value = "" if value is None else str(value)
        if len(text_value) > 255:
            raise InvalidCalculatorContractError(f"{definition.feature_code} 文本输出超过 255 字符")
        return {"numeric_value": None, "bool_value": None, "text_value": text_value}
    raise InvalidCalculatorContractError(f"{definition.feature_code} 使用不支持的 value_type")


CalculatedFeature = tuple[FeatureDefinition, CalculatorOutput, dict[str, Any]]


def _calculate_feature_values(
    *,
    items: tuple[Any, ...],
    definitions: dict[int, FeatureDefinition],
    snapshot: MarketSnapshot,
    kline_input: dict[str, Any],
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> list[CalculatedFeature] | ServiceResult:
    calculated_values: list[CalculatedFeature] = []
    for item in items:
        definition = definitions[item.component_object_id]
        if not definition.is_enabled:
            return _problem_result(
                status=ResultStatus.BLOCKED,
                reason_code="feature_definition_disabled",
                message="特征定义已禁用",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
            )
        actual_params_hash = stable_hash(definition.params)
        if (
            definition.feature_code != item.component_code
            or definition.definition_hash != item.definition_hash
            or definition.algorithm_name != item.algorithm_name
            or definition.algorithm_version != item.algorithm_version
            or definition.params_hash != actual_params_hash
            or item.params_hash != actual_params_hash
        ):
            return _problem_result(
                status=ResultStatus.BLOCKED,
                reason_code="feature_definition_identity_mismatch",
                message="特征定义、算法身份或参数指纹失配",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
                payload_summary={"feature_code": item.component_code},
            )
        result = _run_feature_calculator(
            definition=definition,
            snapshot=snapshot,
            kline_input=kline_input,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            registry=registry,
        )
        if isinstance(result, ServiceResult):
            return result
        calculated_values.append(result)
    return calculated_values


def _run_feature_calculator(
    *,
    definition: FeatureDefinition,
    snapshot: MarketSnapshot,
    kline_input: dict[str, Any],
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> CalculatedFeature | ServiceResult:
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.FEATURE_LAYER,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
        if calculator.metadata.output_schema_version != definition.output_schema_version:
            return _problem_result(
                status=ResultStatus.BLOCKED,
                reason_code="calculator_metadata_mismatch",
                message="calculator metadata 与特征定义不一致",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
            )
        if dry_run and not calculator.metadata.supports_dry_run:
            return _problem_result(
                status=ResultStatus.BLOCKED,
                reason_code="calculator_dry_run_unsupported",
                message="calculator 不支持 dry-run",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
            )
        calculation_input = CalculatorInput(
            calculator_type=CalculatorType.FEATURE_LAYER,
            input_schema_version=calculator.metadata.input_schema_version,
            output_schema_version=definition.output_schema_version,
            upstream_refs={"market_snapshot_id": snapshot.id, "feature_definition_id": definition.id},
            business_time_utc=snapshot.analysis_close_time_utc,
            market_identity={
                "exchange": snapshot.exchange,
                "market_type": snapshot.market_type,
                "symbol": snapshot.symbol,
                "base_timeframe": snapshot.base_timeframe,
                "higher_timeframe": snapshot.higher_timeframe,
            },
            frozen_params=definition.params,
            params_hash=definition.params_hash,
            values={"market_snapshot": kline_input},
            evidence_summary={"definition_hash": definition.definition_hash},
        )
        output = calculator.calculate(calculation_input)
        if not isinstance(output, CalculatorOutput):
            raise InvalidCalculatorContractError("calculator 必须返回 CalculatorOutput")
        if output.output_schema_version != definition.output_schema_version:
            return _problem_result(
                status=ResultStatus.FAILED,
                reason_code="calculator_output_schema_mismatch",
                message="calculator 输出 schema 不匹配",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
            )
        if output.calculation_status == CalculationStatus.FAILED:
            return _problem_result(
                status=ResultStatus.FAILED,
                reason_code=output.error_code or "feature_calculation_failed",
                message=output.error_message or "特征计算失败",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
            )
        return definition, output, _extract_feature_value(definition, output)
    except InvalidCalculatorContractError as exc:
        return _problem_result(
            status=ResultStatus.FAILED,
            reason_code="feature_output_contract_invalid",
            message=str(exc),
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    except StrategyCalculatorError as exc:
        return _problem_result(
            status=ResultStatus.BLOCKED,
            reason_code="calculator_missing_or_invalid",
            message=str(exc),
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    except Exception as exc:
        return _problem_result(
            status=ResultStatus.FAILED,
            reason_code="feature_calculator_unexpected_error",
            message=f"calculator 出现未预期程序异常：{type(exc).__name__}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )


def _persist_feature_set(
    *,
    snapshot: MarketSnapshot,
    release: Any,
    release_hash: str,
    feature_set_key: str,
    feature_schema_version: str,
    definition_set_hash: str,
    calculated_values: list[CalculatedFeature],
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    try:
        with transaction.atomic():
            feature_set = FeatureSet.objects.create(
                feature_set_key=feature_set_key,
                business_request_key=business_request_key,
                market_snapshot=snapshot,
                strategy_analysis_release=release,
                release_hash=release_hash,
                status=AnalysisObjectStatus.CREATED,
                reason_code="feature_set_created",
                is_usable=True,
                allows_atomic_signal=True,
                feature_schema_version=feature_schema_version,
                definition_set_hash=definition_set_hash,
                feature_count=len(calculated_values),
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            FeatureValue.objects.bulk_create(
                [
                    FeatureValue(
                        feature_set=feature_set,
                        feature_definition=definition,
                        feature_code=definition.feature_code,
                        feature_definition_hash=definition.definition_hash,
                        algorithm_name=definition.algorithm_name,
                        algorithm_version=definition.algorithm_version,
                        params_hash=definition.params_hash,
                        value_type=definition.value_type,
                        output_schema_version=definition.output_schema_version,
                        evidence={
                            "evidence_items": _json_ready(output.evidence_items),
                            "calculation_summary": _json_ready(output.calculation_summary),
                        },
                        status=AnalysisObjectStatus.CREATED,
                        is_valid=True,
                        **value_kwargs,
                    )
                    for definition, output, value_kwargs in calculated_values
                ]
            )
    except IntegrityError:
        existing = FeatureSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = FeatureSet.objects.filter(feature_set_key=feature_set_key).first()
        if existing:
            return ServiceResult(
                ResultStatus.SUCCEEDED if existing.status == AnalysisObjectStatus.CREATED else ResultStatus.BLOCKED,
                "feature_set_idempotent_replay",
                "FeatureSet 并发幂等复用",
                trace_id,
                trigger_source,
                {"feature_set_id": existing.id, "feature_set_key": existing.feature_set_key, "persisted": True},
            )
        return _problem_result(
            status=ResultStatus.FAILED,
            reason_code="feature_set_persistence_conflict",
            message="FeatureSet 写入发生非幂等唯一约束冲突",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    except DatabaseError:
        existing = FeatureSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = FeatureSet.objects.filter(feature_set_key=feature_set_key).first()
        if existing and existing.status == AnalysisObjectStatus.CREATED:
            return ServiceResult(
                ResultStatus.SUCCEEDED,
                "feature_set_idempotent_replay",
                "FeatureSet 已确认完整落库",
                trace_id,
                trigger_source,
                {"feature_set_id": existing.id, "feature_set_key": existing.feature_set_key, "persisted": True},
            )
        return _problem_result(
            status=ResultStatus.UNKNOWN,
            reason_code="feature_set_persistence_unknown",
            message="无法安全确认 FeatureSet 是否完整落库",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "feature_set_created",
        "FeatureSet 已创建",
        trace_id,
        trigger_source,
        {
            "feature_set_id": feature_set.id,
            "feature_set_key": feature_set.feature_set_key,
            "persisted": True,
            "feature_count": feature_set.feature_count,
        },
    )


def build_feature_set(
    *,
    market_snapshot_id: int,
    strategy_analysis_release_id: int,
    release_hash: str,
    expected_definition_set_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    existing = FeatureSet.objects.filter(business_request_key=business_request_key).first()
    if existing:
        return ServiceResult(
            ResultStatus.SUCCEEDED if existing.status == AnalysisObjectStatus.CREATED else ResultStatus.BLOCKED,
            "feature_set_idempotent_replay",
            "FeatureSet 幂等复用",
            trace_id,
            trigger_source,
            {"feature_set_id": existing.id, "feature_set_key": existing.feature_set_key, "persisted": True},
        )

    try:
        snapshot = MarketSnapshot.objects.get(id=market_snapshot_id)
    except MarketSnapshot.DoesNotExist:
        if not dry_run:
            _record_block_alert(
                event_key=build_idempotency_key("feature_layer_blocked", business_request_key, "market_snapshot_missing"),
                title_zh="FeatureLayer 阻断：MarketSnapshot 不存在",
                message_zh="特征层没有找到明确的 MarketSnapshot，不能继续。",
                reason_code="market_snapshot_missing",
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        return ServiceResult(ResultStatus.BLOCKED, "market_snapshot_missing", "MarketSnapshot 不存在", trace_id, trigger_source)

    if snapshot.status != CommonStatus.CREATED or not snapshot.allows_feature_layer:
        if not dry_run:
            _record_block_alert(
                event_key=build_idempotency_key("feature_layer_blocked", business_request_key, "market_snapshot_not_consumable"),
                title_zh="FeatureLayer 阻断：MarketSnapshot 不可消费",
                message_zh="MarketSnapshot 状态或放行标记不允许进入特征层。",
                reason_code="market_snapshot_not_consumable",
                trace_id=trace_id,
                trigger_source=trigger_source,
                payload_summary={"market_snapshot_id": market_snapshot_id, "status": snapshot.status},
            )
        return ServiceResult(ResultStatus.BLOCKED, "market_snapshot_not_consumable", "MarketSnapshot 不可消费", trace_id, trigger_source)

    try:
        frozen_slice = resolve_frozen_slice(
            release_id=strategy_analysis_release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
            expected_definition_set_hash=expected_definition_set_hash,
        )
    except (ObjectDoesNotExist, ValueError) as exc:
        if not dry_run:
            _record_block_alert(
                event_key=build_idempotency_key("feature_layer_blocked", business_request_key, "release_slice_invalid"),
                title_zh="FeatureLayer 阻断：版本包切片无效",
                message_zh="特征层收到的版本包身份或切片指纹无效。",
                reason_code="release_slice_invalid",
                trace_id=trace_id,
                trigger_source=trigger_source,
                payload_summary={"error": str(exc)},
            )
        return ServiceResult(ResultStatus.BLOCKED, "release_slice_invalid", "版本包切片无效", trace_id, trigger_source)

    if not frozen_slice.items:
        return _problem_result(
            status=ResultStatus.BLOCKED,
            reason_code="feature_definition_missing",
            message="版本包没有选择任何特征定义",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )

    feature_schema_version = settings.FEATURE_SCHEMA_VERSION
    feature_set_key = stable_hash(
        {
            "market_snapshot_id": snapshot.id,
            "snapshot_key": snapshot.business_request_key,
            "feature_schema_version": feature_schema_version,
            "definition_set_hash": frozen_slice.definition_set_hash,
        }
    )
    existing_by_key = FeatureSet.objects.filter(feature_set_key=feature_set_key).first()
    if existing_by_key:
        return ServiceResult(
            ResultStatus.SUCCEEDED if existing_by_key.status == AnalysisObjectStatus.CREATED else ResultStatus.BLOCKED,
            "feature_set_identity_replay",
            "FeatureSet 输入身份幂等复用",
            trace_id,
            trigger_source,
            {
                "feature_set_id": existing_by_key.id,
                "feature_set_key": existing_by_key.feature_set_key,
                "persisted": True,
            },
        )

    definitions = {
        definition.id: definition
        for definition in FeatureDefinition.objects.filter(id__in=[item.component_object_id for item in frozen_slice.items])
    }
    if len(definitions) != len(frozen_slice.items):
        return _problem_result(
            status=ResultStatus.BLOCKED,
            reason_code="feature_definition_missing",
            message="特征定义缺失",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )

    kline_input, window_error = _market_snapshot_input(snapshot)
    if window_error:
        status = ResultStatus.BLOCKED if window_error == "market_snapshot_domain_mismatch" else ResultStatus.FAILED
        return _problem_result(
            status=status,
            reason_code=window_error,
            message="MarketSnapshot 对应的实际 Kline 窗口不完整或身份不一致",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"market_snapshot_id": snapshot.id},
        )
    if kline_input is None:
        return _problem_result(
            status=ResultStatus.FAILED,
            reason_code="feature_window_payload_missing",
            message="Kline 窗口校验通过但未形成输入",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    calculated_values = _calculate_feature_values(
        items=frozen_slice.items,
        definitions=definitions,
        snapshot=snapshot,
        kline_input=kline_input,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
        registry=registry,
    )
    if isinstance(calculated_values, ServiceResult):
        return calculated_values

    if dry_run:
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "feature_set_dry_run_succeeded",
            "FeatureLayer dry-run 通过",
            trace_id,
            trigger_source,
            {"persisted": False, "feature_count": len(calculated_values), "definition_set_hash": frozen_slice.definition_set_hash},
        )

    return _persist_feature_set(
        snapshot=snapshot,
        release=frozen_slice.release,
        release_hash=release_hash,
        feature_set_key=feature_set_key,
        feature_schema_version=feature_schema_version,
        definition_set_hash=frozen_slice.definition_set_hash,
        calculated_values=calculated_values,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
