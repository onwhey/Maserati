"""RuntimeConfig 模块：计算真实交易最终权限；读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.audit.services import record_audit
from apps.foundation.context import make_trace_id
from apps.foundation.triggers import TriggerSource

from .models import RuntimeTradingConfig


DEFAULT_CONFIG_KEY = "default"


@dataclass(frozen=True)
class EffectiveRealTradingPermission:
    deployment_allowed: bool
    runtime_allowed: bool
    effective_allowed: bool
    fail_closed: bool
    reason_code: str


def get_or_create_runtime_trading_config() -> RuntimeTradingConfig:
    config, _created = RuntimeTradingConfig.objects.get_or_create(
        config_key=DEFAULT_CONFIG_KEY,
        defaults={"runtime_real_trading_permission": False},
    )
    return config


def get_runtime_trading_config() -> RuntimeTradingConfig | None:
    return RuntimeTradingConfig.objects.filter(config_key=DEFAULT_CONFIG_KEY).first()


def get_effective_real_trading_permission() -> EffectiveRealTradingPermission:
    try:
        deployment_allowed = bool(settings.DEPLOYMENT_REAL_TRADING_ENABLED)
        runtime_config = get_runtime_trading_config()
        runtime_allowed = bool(runtime_config and runtime_config.runtime_real_trading_permission)
    except Exception:
        return EffectiveRealTradingPermission(
            deployment_allowed=False,
            runtime_allowed=False,
            effective_allowed=False,
            fail_closed=True,
            reason_code="real_trading_permission_unreadable",
        )

    return EffectiveRealTradingPermission(
        deployment_allowed=deployment_allowed,
        runtime_allowed=runtime_allowed,
        effective_allowed=deployment_allowed and runtime_allowed,
        fail_closed=False,
        reason_code="allowed" if deployment_allowed and runtime_allowed else "real_trading_permission_closed",
    )


def set_runtime_real_trading_permission(
    *,
    enabled: bool,
    operator_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
    trace_id: str | None = None,
    trigger_source: str = TriggerSource.MANAGEMENT_COMMAND,
) -> RuntimeTradingConfig:
    trace = trace_id or make_trace_id()
    evidence = evidence or {}
    with transaction.atomic():
        config = get_or_create_runtime_trading_config()
        before = {"runtime_real_trading_permission": config.runtime_real_trading_permission}
        config.runtime_real_trading_permission = enabled
        config.updated_by = operator_id
        config.updated_reason = reason
        config.save(update_fields=["runtime_real_trading_permission", "updated_by", "updated_reason", "updated_at_utc"])
        after = {"runtime_real_trading_permission": enabled}

        record_audit(
            operator_id=operator_id,
            operation_type="runtime_real_trading_permission_changed",
            target_object_type="RuntimeTradingConfig",
            target_object_id=str(config.id),
            before_state_summary=before,
            after_state_summary=after,
            reason=reason,
            evidence=evidence,
            result="succeeded",
            trace_id=trace,
            trigger_source=str(trigger_source),
        )
        record_alert_event(
            event_key=f"runtime_config:real_trading_permission_changed:{config.id}:{enabled}:{config.updated_at_utc.isoformat()}",
            source_module="runtime_config",
            event_type="real_trading_runtime_permission_changed",
            event_category="safety_control",
            severity=AlertSeverity.WARNING,
            title_zh="真实交易运行开关已变更",
            message_zh="MySQL 中的真实交易运行开关已变更，最终权限仍需同时满足部署级硬权限。",
            trace_id=trace,
            trigger_source=str(trigger_source),
            related_object_type="RuntimeTradingConfig",
            related_object_id=str(config.id),
            business_status="enabled" if enabled else "disabled",
            reason_code="runtime_permission_changed",
            payload_summary={"enabled": enabled},
            delivery_enabled=False,
        )
    return config
