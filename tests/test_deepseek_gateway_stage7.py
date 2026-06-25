from __future__ import annotations

import json

import pytest

from apps.deepseek_gateway.review import FakeDeepSeekReviewGateway, HttpDeepSeekReviewGateway
from apps.deepseek_gateway.types import (
    CALLER_AI_REVIEW,
    CALLER_AI_REVIEW_SERVICE,
    ERROR_CALLER_NOT_ALLOWED,
    ERROR_CREDENTIAL_MISSING,
    ERROR_GATEWAY_DISABLED,
    ERROR_MODEL_PROFILE_INVALID,
    ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
    ERROR_SENSITIVE_CONTENT_DETECTED,
    STATUS_BLOCKED_BEFORE_SEND,
    STATUS_SUCCEEDED,
    DeepSeekGatewayCallContext,
)


class FakeHttpResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def deepseek_context(*, caller_module: str = CALLER_AI_REVIEW, purpose: str = "ai_review") -> DeepSeekGatewayCallContext:
    return DeepSeekGatewayCallContext(
        purpose=purpose,
        caller_module=caller_module,
        review_mode="single_run",
        input_package_hash="package_hash",
        prompt_hash="prompt_hash",
        idempotency_key="review-key",
        trace_id="trace_deepseek_gateway",
        trigger_source="test",
        operator_id="tester",
    )


def messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "你是离线复盘助手，只输出结构化 JSON。"},
        {"role": "user", "content": "请分析这次已经脱敏的复盘数据包。"},
    ]


def enable_deepseek_gateway(settings) -> None:
    settings.DEEPSEEK_GATEWAY_ENABLED = True
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    settings.DEEPSEEK_API_KEY = "deepseek-test-key"
    settings.DEEPSEEK_BASE_URL = "https://deepseek.test"
    settings.DEEPSEEK_DEFAULT_MODEL_PROFILE = "default_review"
    settings.DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
    settings.DEEPSEEK_REVIEW_MODEL = "deepseek-review"
    settings.DEEPSEEK_API_FORMAT = "openai_chat_completions"
    settings.DEEPSEEK_MODEL_PROFILE_ENABLED = True
    settings.DEEPSEEK_JSON_OUTPUT_ENABLED = True
    settings.DEEPSEEK_MAX_INPUT_TOKENS = 16000
    settings.DEEPSEEK_MAX_OUTPUT_TOKENS = 4096
    settings.DEEPSEEK_CONNECT_TIMEOUT_SECONDS = 5
    settings.DEEPSEEK_READ_TIMEOUT_SECONDS = 10


def test_fake_deepseek_gateway_records_ai_review_call_without_real_network() -> None:
    gateway = FakeDeepSeekReviewGateway(output_text='{"summary":"ok"}')

    result = gateway.generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=messages(),
        response_format={"type": "json_object"},
        max_output_tokens=1000,
    )

    assert result.success is True
    assert result.status == STATUS_SUCCEEDED
    assert result.output_text == '{"summary":"ok"}'
    assert result.request_sent is True
    assert gateway.calls[0]["model_profile_code"] == "default_review"


def test_gateway_rejects_non_ai_review_caller_before_send() -> None:
    result = FakeDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(caller_module="OpsConsole"),
        model_profile_code="default_review",
        messages=messages(),
    )

    assert result.success is False
    assert result.status == STATUS_BLOCKED_BEFORE_SEND
    assert result.request_sent is False
    assert result.error_category == ERROR_CALLER_NOT_ALLOWED


def test_gateway_accepts_ai_review_service_caller_without_real_network() -> None:
    result = FakeDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(caller_module=CALLER_AI_REVIEW_SERVICE),
        model_profile_code="default_review",
        messages=messages(),
    )

    assert result.success is True
    assert result.status == STATUS_SUCCEEDED


def test_http_gateway_disabled_blocks_before_send(settings, monkeypatch) -> None:
    settings.DEEPSEEK_GATEWAY_ENABLED = False
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_GATEWAY_DISABLED


def test_http_gateway_blocks_when_real_external_services_disabled(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    settings.ALLOW_REAL_EXTERNAL_SERVICES = False
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_REAL_EXTERNAL_SERVICES_DISABLED


def test_http_gateway_blocks_when_api_key_missing(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    settings.DEEPSEEK_API_KEY = ""
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_CREDENTIAL_MISSING


def test_gateway_rejects_full_model_profile_instead_of_profile_code(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code={"profile_code": "default_review", "model_name": "deepseek-chat"},  # type: ignore[arg-type]
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_MODEL_PROFILE_INVALID
    assert result.model_profile_code == "<invalid_model_profile_code>"
    assert "secret-model" not in result.model_profile_code


def test_gateway_rejects_full_model_profile_without_echoing_payload(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code={"profile_code": "default_review", "api_key": "secret-model"},  # type: ignore[arg-type]
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_MODEL_PROFILE_INVALID
    assert result.model_profile_code == "<invalid_model_profile_code>"
    assert "secret-model" not in str(result)


def test_gateway_rejects_unknown_profile_code_before_send(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="unregistered_profile",
        messages=messages(),
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_MODEL_PROFILE_INVALID


def test_gateway_blocks_sensitive_content_before_send(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", pytest.fail)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=[{"role": "user", "content": "api_key=should-not-leave-process"}],
    )

    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_SENSITIVE_CONTENT_DETECTED


def test_http_gateway_uses_profile_and_returns_sanitized_result(settings, monkeypatch) -> None:
    enable_deepseek_gateway(settings)
    seen_urls: list[str] = []
    seen_headers: list[dict[str, str]] = []
    seen_payloads: list[dict[str, object]] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        seen_headers.append(dict(request.header_items()))
        seen_payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeHttpResponse(
            {
                "id": "chatcmpl-test",
                "model": "deepseek-review",
                "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            }
        )

    monkeypatch.setattr("apps.deepseek_gateway.review.urllib.request.urlopen", fake_urlopen)

    result = HttpDeepSeekReviewGateway().generate_review_completion(
        context=deepseek_context(),
        model_profile_code="default_review",
        messages=messages(),
        response_format={"type": "json_object"},
        max_output_tokens=2048,
    )

    assert result.success is True
    assert result.status == STATUS_SUCCEEDED
    assert result.output_text == '{"summary":"ok"}'
    assert result.attempt_count == 1
    assert seen_urls == ["https://deepseek.test/chat/completions"]
    assert seen_payloads[0]["model"] == "deepseek-review"
    assert seen_payloads[0]["max_tokens"] == 2048
    assert "Authorization" in seen_headers[0]
    assert "deepseek-test-key" not in str(result.sanitized_request_summary)
    assert "deepseek-test-key" not in str(result.sanitized_response_summary)
    assert "请分析这次已经脱敏的复盘数据包" not in str(result.sanitized_request_summary)
    assert result.profile_summary["profile_code"] == "default_review"
    assert result.profile_summary["model_name_configured"] is True
