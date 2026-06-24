"""PriceSnapshot 模块：创建本轮 mark price 事实；读写数据库；访问 Redis 缓存；通过 BinanceGateway 访问 Binance；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.binance_gateway.public_market import PublicMarketGateway, get_public_market_gateway
from apps.binance_gateway.types import BinanceGatewayCallContext, BinanceGatewayResult, normalize_active_market_type
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult

from ..models import PriceSnapshot, PriceType
from .alerts import record_price_snapshot_alert, severity_for_failure
from .hashing import stable_hash


logger = logging.getLogger(__name__)

PRICE_SNAPSHOT_SCHEMA_VERSION = "1.0"
MAX_BUSINESS_REQUEST_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
MAX_ERROR_MESSAGE_LENGTH = 500
ZERO = Decimal("0")


@dataclass(frozen=True)
class PriceSnapshotDraft:
    business_request_key: str
    exchange: str
    market_type: str
    account_domain: str
    symbol: str
    price_type: str
    mark_price: Decimal
    price_unit: str
    source: str
    source_operation: str
    source_update_time_utc: datetime
    requested_at_utc: datetime
    received_at_utc: datetime
    as_of_utc: datetime
    expires_at_utc: datetime
    gateway_latency_ms: int
    gateway_attempt_count: int
    price_snapshot_hash: str
    raw_payload: dict[str, Any]
    gateway_call_summary: dict[str, Any]


def create_price_snapshot(
    *,
    business_request_key: str,
    market_type: str,
    account_domain: str,
    symbol: str,
    trace_id: str,
    trigger_source: str,
    gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    normalized_market = normalize_active_market_type(market_type)
    normalized_symbol = symbol.strip().upper()
    existing = PriceSnapshot.objects.filter(business_request_key=business_request_key).first()
    if existing is not None:
        return _existing_result(
            existing,
            requested_market_type=normalized_market,
            requested_account_domain=account_domain,
            requested_symbol=normalized_symbol,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )

    validation_error, validation_message = _validate_create_request(
        business_request_key=business_request_key,
        market_type=normalized_market,
        account_domain=account_domain,
        symbol=normalized_symbol,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if validation_error:
        return _blocked_result(
            reason_code=validation_error,
            message=validation_message,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary={
                "market_type": normalized_market,
                "account_domain": account_domain,
                "symbol": normalized_symbol,
            },
        )

    if not getattr(settings, "PRICE_SNAPSHOT_ENABLED", False):
        return _blocked_result(
            reason_code="price_snapshot_disabled",
            message="PriceSnapshot 部署级开关未开启",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary={"market_type": normalized_market, "account_domain": account_domain, "symbol": normalized_symbol},
        )

    requested_at = timezone.now()
    gateway_result = (gateway or get_public_market_gateway()).get_mark_price(
        market_type=normalized_market,
        symbol=normalized_symbol,
        call_context=BinanceGatewayCallContext(
            trace_id=trace_id,
            trigger_source=trigger_source,
            operation="get_mark_price",
            market_type=normalized_market,
            symbol=normalized_symbol,
            account_domain=account_domain,
            business_object_type="PriceSnapshot",
            business_object_id=business_request_key,
            request_time_utc=requested_at,
        ),
    )
    received_at = timezone.now()
    if not gateway_result.success or not gateway_result.response_received:
        return _failed_gateway_result(
            gateway_result,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )

    try:
        draft = _build_draft(
            business_request_key=business_request_key,
            market_type=normalized_market,
            account_domain=account_domain,
            symbol=normalized_symbol,
            gateway_result=gateway_result,
            requested_at_utc=gateway_result.request_started_at_utc or requested_at,
            received_at_utc=gateway_result.request_finished_at_utc or received_at,
        )
    except (ValueError, TypeError, InvalidOperation) as exc:
        return _failed_result(
            reason_code=_reason_from_validation_error(str(exc)),
            message=str(exc),
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary=_gateway_summary(gateway_result),
        )

    snapshot, persist_result = _persist_or_recover(draft=draft, trace_id=trace_id, trigger_source=trigger_source)
    if persist_result is not None:
        return persist_result
    assert snapshot is not None
    cache_status = cache_price_snapshot(snapshot, trace_id=trace_id, trigger_source=trigger_source)
    return _snapshot_result(snapshot, trace_id=trace_id, trigger_source=trigger_source, cache_status=cache_status)


def cache_price_snapshot(snapshot: PriceSnapshot, *, trace_id: str, trigger_source: str) -> str:
    if not getattr(settings, "PRICE_SNAPSHOT_REDIS_CACHE_ENABLED", True):
        return "disabled"
    summary = cache_summary_from_snapshot(snapshot)
    seconds = _remaining_seconds(snapshot.expires_at_utc, timezone.now())
    if seconds <= 0:
        return "skipped_expired"
    try:
        cache.set(_cache_key(snapshot.id), summary, timeout=seconds)
    except Exception as exc:
        logger.warning("PriceSnapshot Redis 缓存写入失败 snapshot_id=%s: %s", snapshot.id, exc)
        _write_alert(
            event_type="price_snapshot_cache_failed",
            reason_code="redis_write_failed",
            message="PriceSnapshot 已写入 MySQL，但 Redis 缓存写入失败，消费者可回读 MySQL。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status=ResultStatus.SUCCEEDED.value,
            related_object_id=str(snapshot.id),
            business_request_key=snapshot.business_request_key,
            payload_summary=_model_data(snapshot),
        )
        return "failed"
    return "written"


def cache_summary_from_snapshot(snapshot: PriceSnapshot) -> dict[str, Any]:
    return {
        "price_snapshot_id": snapshot.id,
        "business_request_key": snapshot.business_request_key,
        "exchange": snapshot.exchange,
        "market_type": snapshot.market_type,
        "account_domain": snapshot.account_domain,
        "symbol": snapshot.symbol,
        "price_type": snapshot.price_type,
        "mark_price": str(snapshot.mark_price),
        "price_unit": snapshot.price_unit,
        "source": snapshot.source,
        "source_operation": snapshot.source_operation,
        "source_update_time_utc": snapshot.source_update_time_utc.isoformat(),
        "as_of_utc": snapshot.as_of_utc.isoformat(),
        "expires_at_utc": snapshot.expires_at_utc.isoformat(),
        "price_snapshot_hash": snapshot.price_snapshot_hash,
    }


def price_snapshot_hash_payload(
    *,
    business_request_key: str,
    exchange: str,
    market_type: str,
    account_domain: str,
    symbol: str,
    price_type: str,
    mark_price: Decimal | str,
    price_unit: str,
    source: str,
    source_operation: str,
    source_update_time_utc: datetime | str,
    as_of_utc: datetime | str,
    expires_at_utc: datetime | str,
) -> dict[str, Any]:
    return {
        "schema_version": PRICE_SNAPSHOT_SCHEMA_VERSION,
        "business_request_key": business_request_key,
        "exchange": exchange,
        "market_type": market_type,
        "account_domain": account_domain,
        "symbol": symbol,
        "price_type": price_type,
        "mark_price": canonical_decimal_text(mark_price),
        "price_unit": price_unit,
        "source": source,
        "source_operation": source_operation,
        "source_update_time_utc": _iso(source_update_time_utc),
        "as_of_utc": _iso(as_of_utc),
        "expires_at_utc": _iso(expires_at_utc),
    }


def compute_price_snapshot_hash(payload: dict[str, Any]) -> str:
    return stable_hash(payload)


def canonical_decimal_text(value: Decimal | str) -> str:
    decimal = Decimal(str(value))
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _build_draft(
    *,
    business_request_key: str,
    market_type: str,
    account_domain: str,
    symbol: str,
    gateway_result: BinanceGatewayResult,
    requested_at_utc: datetime,
    received_at_utc: datetime,
) -> PriceSnapshotDraft:
    if gateway_result.market_type != market_type:
        raise ValueError("market_identity_mismatch")
    payload = _extract_mark_price_payload(gateway_result.payload, symbol)
    mark_price = _parse_mark_price(payload)
    _validate_decimal_places(mark_price)
    source_update_time = _parse_source_update_time(payload)
    trusted_now = gateway_result.server_time_utc or received_at_utc
    _validate_price_time(source_update_time, trusted_now)
    ttl_seconds = _ttl_seconds()
    expires_at = source_update_time + timedelta(seconds=ttl_seconds)
    if expires_at <= received_at_utc:
        raise ValueError("mark_price_stale_at_creation")
    price_unit = _derive_price_unit(symbol, payload)
    hash_payload = price_snapshot_hash_payload(
        business_request_key=business_request_key,
        exchange="binance",
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
        price_type=PriceType.MARK_PRICE,
        mark_price=mark_price,
        price_unit=price_unit,
        source="binance_rest",
        source_operation="get_mark_price",
        source_update_time_utc=source_update_time,
        as_of_utc=source_update_time,
        expires_at_utc=expires_at,
    )
    return PriceSnapshotDraft(
        business_request_key=business_request_key,
        exchange="binance",
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
        price_type=PriceType.MARK_PRICE,
        mark_price=mark_price,
        price_unit=price_unit,
        source="binance_rest",
        source_operation="get_mark_price",
        source_update_time_utc=source_update_time,
        requested_at_utc=requested_at_utc,
        received_at_utc=received_at_utc,
        as_of_utc=source_update_time,
        expires_at_utc=expires_at,
        gateway_latency_ms=gateway_result.latency_ms,
        gateway_attempt_count=gateway_result.attempt_count,
        price_snapshot_hash=compute_price_snapshot_hash(hash_payload),
        raw_payload=sanitize_mapping(payload),
        gateway_call_summary=_gateway_summary(gateway_result),
    )


def _persist_or_recover(
    *,
    draft: PriceSnapshotDraft,
    trace_id: str,
    trigger_source: str,
) -> tuple[PriceSnapshot | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            snapshot = PriceSnapshot.objects.create(
                business_request_key=draft.business_request_key,
                exchange=draft.exchange,
                market_type=draft.market_type,
                account_domain=draft.account_domain,
                symbol=draft.symbol,
                price_type=draft.price_type,
                mark_price=draft.mark_price,
                price_unit=draft.price_unit,
                source=draft.source,
                source_operation=draft.source_operation,
                source_update_time_utc=draft.source_update_time_utc,
                requested_at_utc=draft.requested_at_utc,
                received_at_utc=draft.received_at_utc,
                as_of_utc=draft.as_of_utc,
                expires_at_utc=draft.expires_at_utc,
                gateway_latency_ms=draft.gateway_latency_ms,
                gateway_attempt_count=draft.gateway_attempt_count,
                price_snapshot_hash=draft.price_snapshot_hash,
                raw_payload=draft.raw_payload,
                gateway_call_summary=draft.gateway_call_summary,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        return snapshot, None
    except IntegrityError:
        existing = PriceSnapshot.objects.filter(business_request_key=draft.business_request_key).first()
        if existing is not None:
            return existing, None
        return None, _failed_result(
            reason_code="mysql_write_failed",
            message="PriceSnapshot 唯一约束冲突且无法恢复既有记录",
            business_request_key=draft.business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary={"business_request_key": draft.business_request_key},
        )
    except (DatabaseError, ValidationError) as exc:
        return None, _failed_result(
            reason_code="mysql_write_failed",
            message=f"PriceSnapshot 写入 MySQL 失败：{limited_text(exc)}",
            business_request_key=draft.business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            payload_summary={"business_request_key": draft.business_request_key},
        )


def _validate_create_request(
    *,
    business_request_key: str,
    market_type: str,
    account_domain: str,
    symbol: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if not business_request_key:
        return "business_request_key_missing", "business_request_key 不能为空"
    if len(business_request_key) > MAX_BUSINESS_REQUEST_KEY_LENGTH:
        return "business_request_key_invalid", "business_request_key 超过允许长度"
    if not trace_id or not trigger_source or len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "price_snapshot_request_invalid", "trace_id / trigger_source 缺失或过长"
    if market_type != active_market_type():
        return "market_identity_mismatch", "PriceSnapshot 请求 market_type 与 active market domain 不一致"
    if account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return "market_identity_mismatch", "PriceSnapshot 请求 account_domain 与 active account domain 不一致"
    if symbol != active_symbol():
        return "market_identity_mismatch", "PriceSnapshot 请求 symbol 与受控交易标的不一致"
    return "", ""


def _existing_result(
    snapshot: PriceSnapshot,
    *,
    requested_market_type: str,
    requested_account_domain: str,
    requested_symbol: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    if (
        snapshot.market_type != requested_market_type
        or snapshot.account_domain != requested_account_domain
        or snapshot.symbol != requested_symbol
    ):
        return _blocked_result(
            reason_code="cross_cycle_price_snapshot",
            message="business_request_key 已存在，但请求市场身份与既有 PriceSnapshot 不一致",
            business_request_key=snapshot.business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_id=str(snapshot.id),
            payload_summary={
                "existing_price_snapshot_id": snapshot.id,
                "existing_market_type": snapshot.market_type,
                "existing_account_domain": snapshot.account_domain,
                "existing_symbol": snapshot.symbol,
                "requested_market_type": requested_market_type,
                "requested_account_domain": requested_account_domain,
                "requested_symbol": requested_symbol,
            },
        )
    return _snapshot_result(snapshot, trace_id=trace_id, trigger_source=trigger_source, reason_code="price_snapshot_already_exists")


def _snapshot_result(
    snapshot: PriceSnapshot,
    *,
    trace_id: str,
    trigger_source: str,
    cache_status: str = "",
    reason_code: str = "price_snapshot_created",
) -> ServiceResult:
    data = _model_data(snapshot)
    data["cache_write_status"] = cache_status
    return ServiceResult(ResultStatus.SUCCEEDED, reason_code, "PriceSnapshot 已可用", trace_id, trigger_source, data)


def _blocked_result(
    *,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    related_object_id: str = "",
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    _write_alert(
        event_type="price_snapshot_blocked",
        reason_code=reason_code,
        message=message,
        trace_id=trace_id or "missing-trace",
        trigger_source=trigger_source or "unknown",
        business_status=ResultStatus.BLOCKED.value,
        related_object_id=related_object_id,
        business_request_key=business_request_key,
        payload_summary=payload_summary,
    )
    return ServiceResult(
        ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {"price_snapshot_id": int(related_object_id) if related_object_id.isdigit() else None, "persisted": False},
    )


def _failed_gateway_result(
    gateway_result: BinanceGatewayResult,
    *,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    return _failed_result(
        reason_code="mark_price_request_failed",
        message=gateway_result.sanitized_error_message or gateway_result.error_category or "Binance mark price 请求失败",
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        payload_summary=_gateway_summary(gateway_result),
    )


def _failed_result(
    *,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    _write_alert(
        event_type="price_snapshot_failed",
        reason_code=reason_code,
        message=message,
        trace_id=trace_id,
        trigger_source=trigger_source,
        business_status=ResultStatus.FAILED.value,
        business_request_key=business_request_key,
        payload_summary=payload_summary,
    )
    return ServiceResult(
        ResultStatus.FAILED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {"price_snapshot_id": None, "persisted": False},
    )


def _write_alert(
    *,
    event_type: str,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    business_status: str,
    related_object_id: str = "",
    business_request_key: str = "",
    payload_summary: dict[str, Any] | None = None,
) -> None:
    try:
        record_price_snapshot_alert(
            event_type=event_type,
            severity=severity_for_failure(reason_code),
            title_zh=f"PriceSnapshot：{reason_code}",
            message_zh=limited_text(message),
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status=business_status,
            reason_code=reason_code,
            related_object_id=related_object_id,
            business_request_key=business_request_key,
            payload_summary=_json_ready(payload_summary or {}),
        )
    except DatabaseError:
        logger.exception("PriceSnapshot AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)


def _extract_mark_price_payload(payload: Any, symbol: str) -> dict[str, Any]:
    if isinstance(payload, dict) and str(payload.get("symbol") or "").upper() == symbol:
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol:
                return item
    raise ValueError("market_identity_mismatch")


def _parse_mark_price(payload: dict[str, Any]) -> Decimal:
    value = payload.get("markPrice")
    if value in (None, ""):
        raise ValueError("mark_price_missing")
    price = Decimal(str(value))
    if not price.is_finite():
        raise ValueError("mark_price_response_invalid")
    if price <= ZERO:
        raise ValueError("mark_price_non_positive")
    return price


def _validate_decimal_places(value: Decimal) -> None:
    max_places = int(getattr(settings, "PRICE_SNAPSHOT_MAX_DECIMAL_PLACES", 18))
    decimal_places = max(0, -value.as_tuple().exponent)
    if decimal_places > max_places:
        raise ValueError("mark_price_response_invalid")


def _parse_source_update_time(payload: dict[str, Any]) -> datetime:
    raw_time = payload.get("time") or payload.get("updateTime")
    if raw_time in (None, ""):
        raise ValueError("mark_price_time_missing")
    return datetime.fromtimestamp(int(raw_time) / 1000, tz=UTC)


def _validate_price_time(source_update_time: datetime, trusted_now: datetime) -> None:
    if source_update_time.tzinfo is None:
        raise ValueError("mark_price_time_missing")
    trusted = _ensure_utc(trusted_now)
    max_skew_ms = int(getattr(settings, "BINANCE_MAX_CLOCK_SKEW_MS", 1000))
    if source_update_time > trusted + timedelta(milliseconds=max_skew_ms):
        raise ValueError("mark_price_response_invalid")


def _reason_from_validation_error(message: str) -> str:
    known = {
        "market_identity_mismatch",
        "mark_price_missing",
        "mark_price_response_invalid",
        "mark_price_non_positive",
        "mark_price_time_missing",
        "mark_price_stale_at_creation",
    }
    if message in known:
        return message
    return "mark_price_response_invalid"


def _gateway_summary(result: BinanceGatewayResult) -> dict[str, Any]:
    return {
        "operation": result.operation,
        "market_type": result.market_type,
        "request_sent": result.request_sent,
        "response_received": result.response_received,
        "http_status": result.http_status,
        "attempt_count": result.attempt_count,
        "latency_ms": result.latency_ms,
        "error_category": result.error_category,
    }


def _model_data(snapshot: PriceSnapshot) -> dict[str, Any]:
    return {
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
        "persisted": True,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def active_market_type() -> str:
    return normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))


def active_symbol() -> str:
    return str(getattr(settings, "ACTIVE_SYMBOL", "")).strip().upper()


def _ttl_seconds() -> int:
    return int(getattr(settings, "PRICE_SNAPSHOT_TTL_SECONDS", 600))


def _cache_key(price_snapshot_id: int) -> str:
    prefix = str(getattr(settings, "PRICE_SNAPSHOT_REDIS_KEY_PREFIX", "price_snapshot")).strip() or "price_snapshot"
    return f"{prefix}:{price_snapshot_id}"


def _remaining_seconds(expires_at: datetime, reference_time: datetime) -> int:
    return max(0, int((_ensure_utc(expires_at) - _ensure_utc(reference_time)).total_seconds()))


def _derive_price_unit(symbol: str, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("priceUnit") or payload.get("quoteAsset") or "").strip().upper()
    if explicit:
        return explicit
    if symbol.endswith("USDT"):
        return "USDT"
    if "USD" in symbol:
        return "USD"
    return "quote_asset"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return _ensure_utc(value).isoformat()
    return str(value)


def limited_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_ERROR_MESSAGE_LENGTH:
        return text
    return text[: MAX_ERROR_MESSAGE_LENGTH - 1] + "…"
