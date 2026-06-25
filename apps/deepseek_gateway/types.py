"""DeepSeekGateway 模块：定义受限接口合同；不读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不直接调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


CALLER_AI_REVIEW = "AIReview"
CALLER_AI_REVIEW_SERVICE = "AIReviewService"
PURPOSE_AI_REVIEW = "ai_review"

API_FORMAT_OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"

STATUS_SUCCEEDED = "succeeded"
STATUS_BLOCKED_BEFORE_SEND = "blocked_before_send"
STATUS_PROVIDER_REJECTED = "provider_rejected"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_TIMEOUT = "timeout"
STATUS_UNKNOWN_AFTER_SEND = "unknown_after_send"
STATUS_FAILED = "failed"
STATUS_RESPONSE_PARSE_ERROR = "response_parse_error"
STATUS_CONTENT_EMPTY = "content_empty"

ERROR_GATEWAY_DISABLED = "gateway_disabled"
ERROR_REAL_EXTERNAL_SERVICES_DISABLED = "real_external_services_disabled"
ERROR_CALLER_NOT_ALLOWED = "caller_not_allowed"
ERROR_PURPOSE_NOT_ALLOWED = "purpose_not_allowed"
ERROR_CONFIGURATION_ERROR = "configuration_error"
ERROR_CREDENTIAL_MISSING = "credential_missing"
ERROR_MODEL_PROFILE_INVALID = "model_profile_invalid"
ERROR_MODEL_PROFILE_DISABLED = "model_profile_disabled"
ERROR_REQUEST_VALIDATION_FAILED = "request_validation_failed"
ERROR_PAYLOAD_TOO_LARGE = "payload_too_large"
ERROR_SENSITIVE_CONTENT_DETECTED = "sensitive_content_detected"
ERROR_PROVIDER_REJECTED = "provider_rejected"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_PROVIDER_SERVER_ERROR = "provider_server_error"
ERROR_TIMEOUT = "timeout"
ERROR_NETWORK_ERROR = "network_error"
ERROR_UNKNOWN_AFTER_SEND = "unknown_after_send"
ERROR_RESPONSE_SCHEMA_ERROR = "response_schema_error"
ERROR_CONTENT_EMPTY = "content_empty"
ERROR_GATEWAY_FAILED = "gateway_failed"


@dataclass(frozen=True)
class DeepSeekGatewayCallContext:
    purpose: str
    caller_module: str
    review_mode: str
    input_package_hash: str
    prompt_hash: str
    idempotency_key: str
    trace_id: str
    trigger_source: str
    model_profile_code: str = ""
    operator_id: str = ""
    business_object_type: str = ""
    business_object_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeepSeekModelProfile:
    profile_code: str
    model_name: str
    api_format: str = API_FORMAT_OPENAI_CHAT_COMPLETIONS
    thinking_enabled: bool = False
    reasoning_effort: str = ""
    json_output_enabled: bool = True
    max_input_tokens: int = 16_000
    max_output_tokens: int = 4_096
    temperature: Decimal = Decimal("0.2")
    top_p: Decimal = Decimal("1.0")
    timeout_seconds: int = 30
    enabled: bool = True


@dataclass(frozen=True)
class DeepSeekGatewayResult:
    operation: str
    status: str
    success: bool
    model_profile_code: str = ""
    output_text: str = ""
    payload: Any = None
    request_sent: bool = False
    response_received: bool = False
    http_status: int | None = None
    error_category: str = ""
    sanitized_error_message: str = ""
    request_started_at_utc: object | None = None
    request_finished_at_utc: object | None = None
    latency_ms: int = 0
    attempt_count: int = 0
    retryable: bool = False
    token_usage: dict[str, Any] = field(default_factory=dict)
    profile_summary: dict[str, Any] = field(default_factory=dict)
    sanitized_request_summary: dict[str, Any] = field(default_factory=dict)
    sanitized_response_summary: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
