"""PriceSnapshot 模块：按明确 ID 读取并校验价格事实；只读数据库；访问 Redis 缓存；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError

from apps.binance_gateway.types import normalize_active_market_type
from apps.foundation.results import ResultStatus, ServiceResult

from .models import PriceSnapshot, PriceType
from .services.alerts import record_price_snapshot_alert
from .services.snapshot import (
    cache_price_snapshot,
    compute_price_snapshot_hash,
    price_snapshot_hash_payload,
)


def load_price_snapshot_for_trading(
    *,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    expected_market_type: str,
    expected_account_domain: str,
    expected_symbol: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    normalized_market = normalize_active_market_type(expected_market_type)
    normalized_symbol = expected_symbol.strip().upper()
    reference_time = _ensure_utc(reference_time_utc)

    if getattr(settings, "PRICE_SNAPSHOT_REDIS_CACHE_ENABLED", True):
        cached = cache.get(_cache_key(price_snapshot_id))
        cache_result = _validate_cached_summary(
            cached,
            price_snapshot_id=price_snapshot_id,
            reference_time_utc=reference_time,
            expected_market_type=normalized_market,
            expected_account_domain=expected_account_domain,
            expected_symbol=normalized_symbol,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        if cache_result is not None:
            return cache_result

    try:
        snapshot = PriceSnapshot.objects.get(id=price_snapshot_id)
    except PriceSnapshot.DoesNotExist:
        return _blocked("price_snapshot_not_found", "PriceSnapshot 不存在", trace_id, trigger_source)

    validation_error = _validate_model_snapshot(
        snapshot,
        reference_time_utc=reference_time,
        expected_market_type=normalized_market,
        expected_account_domain=expected_account_domain,
        expected_symbol=normalized_symbol,
    )
    if validation_error:
        _write_consume_alert(
            snapshot=snapshot,
            reason_code=validation_error,
            message=f"PriceSnapshot 消费校验失败：{validation_error}",
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        return _blocked(validation_error, "PriceSnapshot 不可供本轮交易链路消费", trace_id, trigger_source, snapshot=snapshot)

    cache_price_snapshot(snapshot, trace_id=trace_id, trigger_source=trigger_source)
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "price_snapshot_loaded",
        "PriceSnapshot 已读取",
        trace_id,
        trigger_source,
        {
            "price_snapshot": snapshot,
            "price_snapshot_id": snapshot.id,
            "business_request_key": snapshot.business_request_key,
            "market_type": snapshot.market_type,
            "account_domain": snapshot.account_domain,
            "symbol": snapshot.symbol,
            "price_type": snapshot.price_type,
            "mark_price": snapshot.mark_price,
            "price_unit": snapshot.price_unit,
            "as_of_utc": snapshot.as_of_utc.isoformat(),
            "expires_at_utc": snapshot.expires_at_utc.isoformat(),
            "price_snapshot_hash": snapshot.price_snapshot_hash,
            "source": "mysql",
        },
    )


def _validate_cached_summary(
    cached: Any,
    *,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    expected_market_type: str,
    expected_account_domain: str,
    expected_symbol: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult | None:
    if cached is None:
        return None
    reason_code = _cached_summary_error(
        cached,
        price_snapshot_id=price_snapshot_id,
        reference_time_utc=reference_time_utc,
        expected_market_type=expected_market_type,
        expected_account_domain=expected_account_domain,
        expected_symbol=expected_symbol,
    )
    if reason_code == "":
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "price_snapshot_loaded_from_cache",
            "PriceSnapshot 已从 Redis 缓存读取",
            trace_id,
            trigger_source,
            {
                **cached,
                "mark_price": Decimal(str(cached["mark_price"])),
                "source": "redis",
            },
        )
    if reason_code in {"price_snapshot_stale", "cross_cycle_price_snapshot"}:
        _write_cache_alert(
            price_snapshot_id=price_snapshot_id,
            reason_code=reason_code,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary=cached if isinstance(cached, dict) else {},
        )
        return _blocked(reason_code, "PriceSnapshot 缓存不可供本轮交易链路消费", trace_id, trigger_source)
    _write_cache_alert(
        price_snapshot_id=price_snapshot_id,
        reason_code=reason_code,
        trace_id=trace_id,
        trigger_source=trigger_source,
        payload_summary=cached if isinstance(cached, dict) else {},
    )
    return None


def _cached_summary_error(
    cached: Any,
    *,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    expected_market_type: str,
    expected_account_domain: str,
    expected_symbol: str,
) -> str:
    if not isinstance(cached, dict):
        return "price_snapshot_cache_invalid"
    required = {
        "price_snapshot_id",
        "business_request_key",
        "exchange",
        "market_type",
        "account_domain",
        "symbol",
        "price_type",
        "mark_price",
        "price_unit",
        "source",
        "source_operation",
        "source_update_time_utc",
        "as_of_utc",
        "expires_at_utc",
        "price_snapshot_hash",
    }
    if not required.issubset(cached):
        return "price_snapshot_cache_invalid"
    if int(cached["price_snapshot_id"]) != price_snapshot_id:
        return "cross_cycle_price_snapshot"
    if (
        cached["market_type"] != expected_market_type
        or cached["account_domain"] != expected_account_domain
        or cached["symbol"] != expected_symbol
        or cached["price_type"] != PriceType.MARK_PRICE
    ):
        return "cross_cycle_price_snapshot"
    try:
        mark_price = Decimal(str(cached["mark_price"]))
        expires_at = _parse_datetime(cached["expires_at_utc"])
        source_update_time = _parse_datetime(cached["source_update_time_utc"])
        as_of = _parse_datetime(cached["as_of_utc"])
    except (InvalidOperation, ValueError, TypeError):
        return "price_snapshot_cache_invalid"
    if mark_price <= 0:
        return "price_snapshot_cache_invalid"
    if reference_time_utc > expires_at:
        return "price_snapshot_stale"
    expected_hash = compute_price_snapshot_hash(
        price_snapshot_hash_payload(
            business_request_key=cached["business_request_key"],
            exchange=cached["exchange"],
            market_type=cached["market_type"],
            account_domain=cached["account_domain"],
            symbol=cached["symbol"],
            price_type=cached["price_type"],
            mark_price=cached["mark_price"],
            price_unit=cached["price_unit"],
            source=cached["source"],
            source_operation=cached["source_operation"],
            source_update_time_utc=source_update_time,
            as_of_utc=as_of,
            expires_at_utc=expires_at,
        )
    )
    if expected_hash != cached["price_snapshot_hash"]:
        return "price_snapshot_hash_mismatch"
    return ""


def _validate_model_snapshot(
    snapshot: PriceSnapshot,
    *,
    reference_time_utc: datetime,
    expected_market_type: str,
    expected_account_domain: str,
    expected_symbol: str,
) -> str:
    if (
        snapshot.market_type != expected_market_type
        or snapshot.account_domain != expected_account_domain
        or snapshot.symbol != expected_symbol
    ):
        return "cross_cycle_price_snapshot"
    if snapshot.price_type != PriceType.MARK_PRICE or snapshot.mark_price <= 0:
        return "price_snapshot_invalid"
    if reference_time_utc > snapshot.expires_at_utc:
        return "price_snapshot_stale"
    expected_hash = compute_price_snapshot_hash(
        price_snapshot_hash_payload(
            business_request_key=snapshot.business_request_key,
            exchange=snapshot.exchange,
            market_type=snapshot.market_type,
            account_domain=snapshot.account_domain,
            symbol=snapshot.symbol,
            price_type=snapshot.price_type,
            mark_price=snapshot.mark_price,
            price_unit=snapshot.price_unit,
            source=snapshot.source,
            source_operation=snapshot.source_operation,
            source_update_time_utc=snapshot.source_update_time_utc,
            as_of_utc=snapshot.as_of_utc,
            expires_at_utc=snapshot.expires_at_utc,
        )
    )
    if expected_hash != snapshot.price_snapshot_hash:
        return "price_snapshot_hash_mismatch"
    return ""


def _blocked(
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    *,
    snapshot: PriceSnapshot | None = None,
) -> ServiceResult:
    return ServiceResult(
        ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {
            "price_snapshot_id": snapshot.id if snapshot else None,
            "business_request_key": snapshot.business_request_key if snapshot else "",
        },
    )


def _write_consume_alert(
    *,
    snapshot: PriceSnapshot,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
) -> None:
    try:
        record_price_snapshot_alert(
            event_type="price_snapshot_consumption_blocked",
            severity="warning",
            title_zh=f"PriceSnapshot 消费被阻断：{reason_code}",
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status=ResultStatus.BLOCKED.value,
            reason_code=reason_code,
            related_object_id=str(snapshot.id),
            business_request_key=snapshot.business_request_key,
            payload_summary={
                "price_snapshot_id": snapshot.id,
                "market_type": snapshot.market_type,
                "account_domain": snapshot.account_domain,
                "symbol": snapshot.symbol,
                "expires_at_utc": snapshot.expires_at_utc.isoformat(),
            },
        )
    except DatabaseError:
        return


def _write_cache_alert(
    *,
    price_snapshot_id: int,
    reason_code: str,
    trace_id: str,
    trigger_source: str,
    payload_summary: dict[str, Any],
) -> None:
    try:
        record_price_snapshot_alert(
            event_type="price_snapshot_cache_invalid",
            severity="warning",
            title_zh=f"PriceSnapshot 缓存异常：{reason_code}",
            message_zh="PriceSnapshot Redis 缓存不可用或不可消费，系统将按规则回读同一条 MySQL 事实或阻断。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status=ResultStatus.BLOCKED.value,
            reason_code=reason_code,
            related_object_id=str(price_snapshot_id),
            payload_summary=payload_summary,
        )
    except DatabaseError:
        return


def _cache_key(price_snapshot_id: int) -> str:
    prefix = str(getattr(settings, "PRICE_SNAPSHOT_REDIS_KEY_PREFIX", "price_snapshot")).strip() or "price_snapshot"
    return f"{prefix}:{price_snapshot_id}"


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
