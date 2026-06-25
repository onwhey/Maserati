"""DeepSeekGateway 模块：提供 AIReview 离线复盘受限访问；不读写数据库；可选访问 Redis 留给后续限频实现；可访问外部 DeepSeek；不发送 Hermes；调用大模型仅限离线复盘；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from django.conf import settings
from django.utils import timezone

from apps.foundation.redaction import sanitize_mapping, sanitize_value

from .types import (
    API_FORMAT_OPENAI_CHAT_COMPLETIONS,
    CALLER_AI_REVIEW,
    CALLER_AI_REVIEW_SERVICE,
    ERROR_CALLER_NOT_ALLOWED,
    ERROR_CONFIGURATION_ERROR,
    ERROR_CONTENT_EMPTY,
    ERROR_CREDENTIAL_MISSING,
    ERROR_GATEWAY_DISABLED,
    ERROR_GATEWAY_FAILED,
    ERROR_MODEL_PROFILE_DISABLED,
    ERROR_MODEL_PROFILE_INVALID,
    ERROR_NETWORK_ERROR,
    ERROR_PAYLOAD_TOO_LARGE,
    ERROR_PROVIDER_REJECTED,
    ERROR_PROVIDER_SERVER_ERROR,
    ERROR_PURPOSE_NOT_ALLOWED,
    ERROR_RATE_LIMITED,
    ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
    ERROR_REQUEST_VALIDATION_FAILED,
    ERROR_RESPONSE_SCHEMA_ERROR,
    ERROR_SENSITIVE_CONTENT_DETECTED,
    ERROR_TIMEOUT,
    ERROR_UNKNOWN_AFTER_SEND,
    PURPOSE_AI_REVIEW,
    STATUS_BLOCKED_BEFORE_SEND,
    STATUS_CONTENT_EMPTY,
    STATUS_FAILED,
    STATUS_PROVIDER_REJECTED,
    STATUS_RATE_LIMITED,
    STATUS_RESPONSE_PARSE_ERROR,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
    STATUS_UNKNOWN_AFTER_SEND,
    DeepSeekGatewayCallContext,
    DeepSeekGatewayResult,
    DeepSeekModelProfile,
)


LOGGER = logging.getLogger(__name__)

OPERATION_GENERATE_REVIEW_COMPLETION = "generate_review_completion"

ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant"}
SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"authorization\s*[:=]\s*[^\s]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret|token|password|signature)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"(mysql|postgres|redis)://[^\s]+", re.IGNORECASE),
    re.compile(r"BEGIN\s+(RSA\s+)?PRIVATE\s+KEY", re.IGNORECASE),
]


class DeepSeekReviewGateway(Protocol):
    def generate_review_completion(
        self,
        *,
        context: DeepSeekGatewayCallContext,
        model_profile_code: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> DeepSeekGatewayResult: ...


class FakeDeepSeekReviewGateway:
    """测试替身：记录 AIReview 复盘调用，不访问真实 DeepSeek。"""

    def __init__(
        self,
        *,
        output_text: str = '{"summary":"fake review"}',
        payload: dict[str, Any] | None = None,
        fail_status: str = "",
        fail_error_category: str = ERROR_GATEWAY_FAILED,
    ) -> None:
        self.output_text = output_text
        self.payload = payload
        self.fail_status = fail_status
        self.fail_error_category = fail_error_category
        self.calls: list[dict[str, Any]] = []

    def generate_review_completion(
        self,
        *,
        context: DeepSeekGatewayCallContext,
        model_profile_code: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> DeepSeekGatewayResult:
        self.calls.append(
            {
                "context": context,
                "model_profile_code": model_profile_code,
                "messages": messages,
                "response_format": response_format,
                "max_output_tokens": max_output_tokens,
            }
        )
        fake_profile = DeepSeekModelProfile(profile_code=str(model_profile_code), model_name="fake") if isinstance(model_profile_code, str) else None
        blocked = validate_common_call(
            context=context,
            model_profile_code=model_profile_code,
            messages=messages,
            profile=fake_profile,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
        )
        if blocked is not None:
            return blocked
        if self.fail_status:
            return DeepSeekGatewayResult(
                operation=OPERATION_GENERATE_REVIEW_COMPLETION,
                status=self.fail_status,
                success=False,
                model_profile_code=str(model_profile_code),
                request_sent=True,
                response_received=self.fail_status != STATUS_TIMEOUT,
                error_category=self.fail_error_category,
                sanitized_error_message=self.fail_error_category,
                attempt_count=1,
                trace_id=context.trace_id,
            )
        payload = self.payload or {
            "choices": [{"message": {"content": self.output_text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return DeepSeekGatewayResult(
            operation=OPERATION_GENERATE_REVIEW_COMPLETION,
            status=STATUS_SUCCEEDED,
            success=True,
            model_profile_code=str(model_profile_code),
            output_text=self.output_text,
            payload=payload,
            request_sent=True,
            response_received=True,
            http_status=200,
            attempt_count=1,
            token_usage=dict(payload.get("usage", {})) if isinstance(payload, dict) else {},
            profile_summary={"profile_code": str(model_profile_code), "fake": True},
            sanitized_request_summary=summarize_request(messages=messages, response_format=response_format, max_output_tokens=max_output_tokens),
            sanitized_response_summary=summarize_response(payload=payload, output_text=self.output_text),
            trace_id=context.trace_id,
        )


class HttpDeepSeekReviewGateway:
    """真实 DeepSeek 复盘 Gateway：只用于 AIReview 离线复盘，不暴露通用聊天接口。"""

    def generate_review_completion(
        self,
        *,
        context: DeepSeekGatewayCallContext,
        model_profile_code: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> DeepSeekGatewayResult:
        profile = resolve_model_profile(model_profile_code)
        blocked = validate_common_call(
            context=context,
            model_profile_code=model_profile_code,
            messages=messages,
            profile=profile,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
        )
        if blocked is not None:
            return blocked

        assert profile is not None
        blocked_by_settings = validate_external_settings(context=context, profile=profile)
        if blocked_by_settings is not None:
            return blocked_by_settings

        started = timezone.now()
        payload = build_request_payload(
            profile=profile,
            messages=messages,
            response_format=response_format,
            max_output_tokens=max_output_tokens,
        )
        url = completion_url()
        headers = request_headers(getattr(settings, "DEEPSEEK_API_KEY", ""))
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=request_body, method="POST", headers=headers)

        try:
            with urllib.request.urlopen(request, timeout=float(profile.timeout_seconds)) as response:
                raw_body = response.read().decode("utf-8")
                provider_payload = json.loads(raw_body)
                return success_or_schema_failure(
                    context=context,
                    profile=profile,
                    provider_payload=provider_payload,
                    http_status=getattr(response, "status", 200),
                    started=started,
                    attempt_count=1,
                    request_summary=summarize_request(
                        messages=messages,
                        response_format=response_format,
                        max_output_tokens=payload.get("max_tokens"),
                    ),
                )
        except urllib.error.HTTPError as exc:
            return http_error_result(context=context, profile=profile, exc=exc, started=started)
        except TimeoutError:
            return request_failure_result(
                context=context,
                profile=profile,
                status=STATUS_TIMEOUT,
                error_category=ERROR_TIMEOUT,
                started=started,
                request_sent=True,
                response_received=False,
            )
        except socket.timeout:
            return request_failure_result(
                context=context,
                profile=profile,
                status=STATUS_TIMEOUT,
                error_category=ERROR_TIMEOUT,
                started=started,
                request_sent=True,
                response_received=False,
            )
        except urllib.error.URLError as exc:
            return request_failure_result(
                context=context,
                profile=profile,
                status=STATUS_UNKNOWN_AFTER_SEND,
                error_category=ERROR_UNKNOWN_AFTER_SEND,
                started=started,
                request_sent=True,
                response_received=False,
                sanitized_error_message=sanitize_text(str(getattr(exc, "reason", ""))),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return request_failure_result(
                context=context,
                profile=profile,
                status=STATUS_RESPONSE_PARSE_ERROR,
                error_category=ERROR_RESPONSE_SCHEMA_ERROR,
                started=started,
                request_sent=True,
                response_received=True,
            )
        except Exception as exc:
            LOGGER.warning("DeepSeek gateway unexpected failure: %s", sanitize_mapping({"error": type(exc).__name__}))
            return request_failure_result(
                context=context,
                profile=profile,
                status=STATUS_FAILED,
                error_category=ERROR_GATEWAY_FAILED,
                started=started,
                request_sent=True,
                response_received=False,
                sanitized_error_message=type(exc).__name__,
            )


def resolve_model_profile(model_profile_code: Any) -> DeepSeekModelProfile | None:
    if not isinstance(model_profile_code, str) or not model_profile_code.strip():
        return None
    profile_code = model_profile_code.strip()
    if profile_code != getattr(settings, "DEEPSEEK_DEFAULT_MODEL_PROFILE", "default_review"):
        return None
    return DeepSeekModelProfile(
        profile_code=profile_code,
        model_name=getattr(settings, "DEEPSEEK_REVIEW_MODEL", "") or getattr(settings, "DEEPSEEK_DEFAULT_MODEL", "deepseek-chat"),
        api_format=getattr(settings, "DEEPSEEK_API_FORMAT", API_FORMAT_OPENAI_CHAT_COMPLETIONS),
        thinking_enabled=bool(getattr(settings, "DEEPSEEK_REASONING_ENABLED", False)),
        reasoning_effort=getattr(settings, "DEEPSEEK_REASONING_EFFORT", ""),
        json_output_enabled=bool(getattr(settings, "DEEPSEEK_JSON_OUTPUT_ENABLED", True)),
        max_input_tokens=int(getattr(settings, "DEEPSEEK_MAX_INPUT_TOKENS", 16_000)),
        max_output_tokens=int(getattr(settings, "DEEPSEEK_MAX_OUTPUT_TOKENS", 4_096)),
        temperature=decimal_setting("DEEPSEEK_TEMPERATURE", Decimal("0.2")),
        top_p=decimal_setting("DEEPSEEK_TOP_P", Decimal("1.0")),
        timeout_seconds=max(
            1,
            int(
                max(
                    getattr(settings, "DEEPSEEK_CONNECT_TIMEOUT_SECONDS", 10),
                    getattr(settings, "DEEPSEEK_READ_TIMEOUT_SECONDS", 30),
                )
            ),
        ),
        enabled=bool(getattr(settings, "DEEPSEEK_MODEL_PROFILE_ENABLED", True)),
    )


def decimal_setting(name: str, default: Decimal) -> Decimal:
    try:
        value = Decimal(str(getattr(settings, name, default)))
    except (InvalidOperation, ValueError):
        return default
    return value if value.is_finite() else default


def validate_common_call(
    *,
    context: DeepSeekGatewayCallContext,
    model_profile_code: Any,
    messages: Any,
    profile: DeepSeekModelProfile | None,
    max_output_tokens: int | None,
    response_format: dict[str, Any] | None,
) -> DeepSeekGatewayResult | None:
    if normalize_caller(context.caller_module) not in allowed_callers():
        return blocked_result(context, safe_model_profile_code(model_profile_code), ERROR_CALLER_NOT_ALLOWED)
    if context.purpose != PURPOSE_AI_REVIEW:
        return blocked_result(context, safe_model_profile_code(model_profile_code), ERROR_PURPOSE_NOT_ALLOWED)
    if not isinstance(model_profile_code, str) or not model_profile_code.strip():
        return blocked_result(context, safe_model_profile_code(model_profile_code), ERROR_MODEL_PROFILE_INVALID)
    if profile is None:
        return blocked_result(context, model_profile_code, ERROR_MODEL_PROFILE_INVALID)
    if not profile.enabled:
        return blocked_result(context, model_profile_code, ERROR_MODEL_PROFILE_DISABLED, profile=profile)
    if profile.api_format != API_FORMAT_OPENAI_CHAT_COMPLETIONS:
        return blocked_result(context, model_profile_code, ERROR_CONFIGURATION_ERROR, profile=profile)
    message_error = validate_messages(messages, profile=profile)
    if message_error:
        return blocked_result(context, model_profile_code, message_error, profile=profile)
    if max_output_tokens is not None and (not isinstance(max_output_tokens, int) or max_output_tokens <= 0):
        return blocked_result(context, model_profile_code, ERROR_REQUEST_VALIDATION_FAILED, profile=profile)
    if max_output_tokens is not None and max_output_tokens > profile.max_output_tokens:
        return blocked_result(context, model_profile_code, ERROR_REQUEST_VALIDATION_FAILED, profile=profile)
    if response_format is not None and not isinstance(response_format, dict):
        return blocked_result(context, model_profile_code, ERROR_REQUEST_VALIDATION_FAILED, profile=profile)
    return None


def validate_external_settings(*, context: DeepSeekGatewayCallContext, profile: DeepSeekModelProfile) -> DeepSeekGatewayResult | None:
    if not getattr(settings, "DEEPSEEK_GATEWAY_ENABLED", False):
        return blocked_result(context, profile.profile_code, ERROR_GATEWAY_DISABLED, profile=profile)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return blocked_result(context, profile.profile_code, ERROR_REAL_EXTERNAL_SERVICES_DISABLED, profile=profile)
    if not getattr(settings, "DEEPSEEK_BASE_URL", ""):
        return blocked_result(context, profile.profile_code, ERROR_CONFIGURATION_ERROR, profile=profile)
    if not getattr(settings, "DEEPSEEK_API_KEY", ""):
        return blocked_result(context, profile.profile_code, ERROR_CREDENTIAL_MISSING, profile=profile)
    if not profile.model_name:
        return blocked_result(context, profile.profile_code, ERROR_CONFIGURATION_ERROR, profile=profile)
    return None


def validate_messages(messages: Any, *, profile: DeepSeekModelProfile) -> str:
    if not isinstance(messages, list) or not messages:
        return ERROR_REQUEST_VALIDATION_FAILED
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            return ERROR_REQUEST_VALIDATION_FAILED
        role = message.get("role")
        content = message.get("content")
        if role not in ALLOWED_MESSAGE_ROLES:
            return ERROR_REQUEST_VALIDATION_FAILED
        if not isinstance(content, str) or not content.strip():
            return ERROR_REQUEST_VALIDATION_FAILED
        total_chars += len(content)
        if contains_sensitive_text(content):
            return ERROR_SENSITIVE_CONTENT_DETECTED
    if total_chars > profile.max_input_tokens * 4:
        return ERROR_PAYLOAD_TOO_LARGE
    return ""


def contains_sensitive_text(value: str) -> bool:
    api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
    if api_key and api_key in value:
        return True
    return any(pattern.search(value) for pattern in SENSITIVE_TEXT_PATTERNS)


def normalize_caller(value: str) -> str:
    return str(value or "").replace("_", "").replace("-", "").lower()


def allowed_callers() -> set[str]:
    return {
        normalize_caller(CALLER_AI_REVIEW),
        normalize_caller(CALLER_AI_REVIEW_SERVICE),
    }


def safe_model_profile_code(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return "<invalid_model_profile_code>"


def build_request_payload(
    *,
    profile: DeepSeekModelProfile,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None,
    max_output_tokens: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": profile.model_name,
        "messages": messages,
        "temperature": float(profile.temperature),
        "top_p": float(profile.top_p),
        "max_tokens": max_output_tokens or profile.max_output_tokens,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if profile.reasoning_effort:
        payload["reasoning_effort"] = profile.reasoning_effort
    return payload


def completion_url() -> str:
    return f"{getattr(settings, 'DEEPSEEK_BASE_URL', '').rstrip('/')}/chat/completions"


def request_headers(api_key: str) -> dict[str, str]:
    return {
        "User-Agent": "the-cypto/deepseek-review",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def success_or_schema_failure(
    *,
    context: DeepSeekGatewayCallContext,
    profile: DeepSeekModelProfile,
    provider_payload: Mapping[str, Any],
    http_status: int,
    started: object,
    attempt_count: int,
    request_summary: dict[str, Any],
) -> DeepSeekGatewayResult:
    content = extract_output_text(provider_payload)
    if content is None:
        return request_failure_result(
            context=context,
            profile=profile,
            status=STATUS_RESPONSE_PARSE_ERROR,
            error_category=ERROR_RESPONSE_SCHEMA_ERROR,
            started=started,
            request_sent=True,
            response_received=True,
            http_status=http_status,
            attempt_count=attempt_count,
        )
    if content.strip() == "":
        return request_failure_result(
            context=context,
            profile=profile,
            status=STATUS_CONTENT_EMPTY,
            error_category=ERROR_CONTENT_EMPTY,
            started=started,
            request_sent=True,
            response_received=True,
            http_status=http_status,
            attempt_count=attempt_count,
        )
    finished = timezone.now()
    return DeepSeekGatewayResult(
        operation=OPERATION_GENERATE_REVIEW_COMPLETION,
        status=STATUS_SUCCEEDED,
        success=True,
        model_profile_code=profile.profile_code,
        output_text=content,
        payload=dict(provider_payload),
        request_sent=True,
        response_received=True,
        http_status=http_status,
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=latency_ms(started, finished),
        attempt_count=attempt_count,
        token_usage=extract_usage(provider_payload),
        profile_summary=profile_summary(profile),
        sanitized_request_summary=request_summary,
        sanitized_response_summary=summarize_response(payload=provider_payload, output_text=content),
        trace_id=context.trace_id,
    )


def extract_output_text(provider_payload: Mapping[str, Any]) -> str | None:
    choices = provider_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    message = first.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def extract_usage(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    usage = provider_payload.get("usage")
    return dict(usage) if isinstance(usage, Mapping) else {}


def http_error_result(
    *,
    context: DeepSeekGatewayCallContext,
    profile: DeepSeekModelProfile,
    exc: urllib.error.HTTPError,
    started: object,
) -> DeepSeekGatewayResult:
    category, status, retryable = classify_http_error(exc.code)
    return request_failure_result(
        context=context,
        profile=profile,
        status=status,
        error_category=category,
        started=started,
        request_sent=True,
        response_received=True,
        http_status=exc.code,
        retryable=retryable,
        sanitized_error_message=read_http_error_message(exc, category),
    )


def classify_http_error(http_status: int) -> tuple[str, str, bool]:
    if http_status == 429:
        return ERROR_RATE_LIMITED, STATUS_RATE_LIMITED, True
    if http_status in {401, 403, 400, 422}:
        return ERROR_PROVIDER_REJECTED, STATUS_PROVIDER_REJECTED, False
    if http_status in {500, 502, 503, 504}:
        return ERROR_PROVIDER_SERVER_ERROR, STATUS_FAILED, True
    return ERROR_PROVIDER_REJECTED, STATUS_PROVIDER_REJECTED, False


def read_http_error_message(exc: urllib.error.HTTPError, fallback: str) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return fallback
    return sanitize_text(body)[:300] or fallback


def blocked_result(
    context: DeepSeekGatewayCallContext,
    model_profile_code: str,
    reason: str,
    *,
    profile: DeepSeekModelProfile | None = None,
) -> DeepSeekGatewayResult:
    return DeepSeekGatewayResult(
        operation=OPERATION_GENERATE_REVIEW_COMPLETION,
        status=STATUS_BLOCKED_BEFORE_SEND,
        success=False,
        model_profile_code=model_profile_code,
        request_sent=False,
        response_received=False,
        error_category=reason,
        sanitized_error_message=reason,
        attempt_count=0,
        retryable=False,
        profile_summary=profile_summary(profile) if profile is not None else {},
        trace_id=context.trace_id,
    )


def request_failure_result(
    *,
    context: DeepSeekGatewayCallContext,
    profile: DeepSeekModelProfile,
    status: str,
    error_category: str,
    started: object,
    request_sent: bool,
    response_received: bool,
    http_status: int | None = None,
    attempt_count: int = 1,
    retryable: bool = False,
    sanitized_error_message: str = "",
) -> DeepSeekGatewayResult:
    finished = timezone.now()
    return DeepSeekGatewayResult(
        operation=OPERATION_GENERATE_REVIEW_COMPLETION,
        status=status,
        success=False,
        model_profile_code=profile.profile_code,
        request_sent=request_sent,
        response_received=response_received,
        http_status=http_status,
        error_category=error_category,
        sanitized_error_message=sanitize_text(sanitized_error_message or error_category),
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=latency_ms(started, finished),
        attempt_count=attempt_count,
        retryable=retryable,
        profile_summary=profile_summary(profile),
        trace_id=context.trace_id,
    )


def profile_summary(profile: DeepSeekModelProfile) -> dict[str, Any]:
    payload = asdict(profile)
    payload.pop("model_name", None)
    payload["model_name_configured"] = bool(profile.model_name)
    payload["temperature"] = str(profile.temperature)
    payload["top_p"] = str(profile.top_p)
    return payload


def summarize_request(
    *,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None,
    max_output_tokens: int | None,
) -> dict[str, Any]:
    total_chars = sum(len(str(message.get("content", ""))) for message in messages if isinstance(message, dict))
    roles = [message.get("role") for message in messages if isinstance(message, dict)]
    return sanitize_mapping(
        {
            "message_count": len(messages),
            "message_roles": roles,
            "total_content_chars": total_chars,
            "response_format": response_format,
            "max_output_tokens": max_output_tokens,
        }
    )


def summarize_response(*, payload: Any, output_text: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"output_chars": len(output_text)}
    if isinstance(payload, Mapping):
        summary["usage"] = sanitize_value(payload.get("usage", {}))
        choices = payload.get("choices")
        summary["choice_count"] = len(choices) if isinstance(choices, list) else 0
        summary["provider_model_present"] = bool(payload.get("model"))
    return summary


def sanitize_text(value: str) -> str:
    sanitized = str(value)
    api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def latency_ms(started: object, finished: object) -> int:
    try:
        return max(0, int((finished - started).total_seconds() * 1000))
    except Exception:
        return 0
