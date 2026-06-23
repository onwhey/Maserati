"""项目底座模块：负责敏感信息脱敏；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYWORDS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "signature",
    "cookie",
    "webhook",
)

SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password|signature)=([^&\s]+)", re.IGNORECASE),
    re.compile(r"(authorization:\s*)([^\s]+)", re.IGNORECASE),
]


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        sanitized[key] = "[REDACTED]" if is_sensitive_key(str(key)) else sanitize_value(value)
    return sanitized

