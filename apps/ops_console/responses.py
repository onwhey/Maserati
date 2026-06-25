"""OpsConsole 模块：统一 API 响应；不读写数据库，不访问 Redis，不访问外部服务，不发送 Hermes，不调用大模型，不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from django.http import JsonResponse


def ok_response(data: Any, *, reason_code: str = "ok", status: int = 200) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "reason_code": reason_code,
            "data": data,
        },
        status=status,
    )


def error_response(*, reason_code: str, message_zh: str, status: int) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "reason_code": reason_code,
            "message_zh": message_zh,
            "data": None,
        },
        status=status,
    )

