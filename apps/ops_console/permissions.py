"""OpsConsole 模块：后端权限校验；读 Django 用户/组权限，不访问 Redis，不访问外部服务，不发送 Hermes，不调用大模型，不涉及交易执行。"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .responses import error_response


VIEW_GROUPS = frozenset({"readonly", "ops_operator", "review_exporter", "admin"})

ACTION_GROUPS: dict[str, frozenset[str]] = {
    "view_ops_console": VIEW_GROUPS,
    "refresh_account_overview": frozenset({"ops_operator", "admin"}),
    "controlled_order_status_recheck": frozenset({"ops_operator", "admin"}),
    "controlled_fill_sync": frozenset({"ops_operator", "admin"}),
    "manual_active_lock_closeout": frozenset({"ops_operator", "admin"}),
    "manage_runtime_guard_issue": frozenset({"ops_operator", "admin"}),
    "manage_review_dataset": frozenset({"ops_operator", "review_exporter", "admin"}),
}


def has_ops_permission(user: AbstractBaseUser, action: str) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    if user.has_perm(f"ops_console.{action}"):
        return True
    allowed_groups = ACTION_GROUPS.get(action, frozenset())
    return user.groups.filter(name__in=allowed_groups).exists()


def require_ops_permission(
    action: str,
    *,
    methods: tuple[str, ...] = ("GET",),
) -> Callable[[Callable[..., JsonResponse]], Callable[..., JsonResponse]]:
    def decorator(view_func: Callable[..., JsonResponse]) -> Callable[..., JsonResponse]:
        @wraps(view_func)
        @require_http_methods(methods)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
            if not request.user.is_authenticated:
                return error_response(
                    reason_code="ops_console_login_required",
                    message_zh="OpsConsole API 需要先登录。",
                    status=401,
                )
            if not has_ops_permission(request.user, action):
                return error_response(
                    reason_code="ops_console_permission_denied",
                    message_zh="当前用户没有访问该 OpsConsole API 的权限。",
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
