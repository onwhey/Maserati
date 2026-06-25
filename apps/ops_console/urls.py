"""OpsConsole 模块：后端查询与受控人工操作 API 路由；不承载业务逻辑，不直接访问外部服务，不提交订单。"""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "ops_console"

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("runs/", views.runs_view, name="runs"),
    path("runs/<int:run_id>/", views.run_detail_view, name="run_detail"),
    path("orders/", views.orders_view, name="orders"),
    path("orders/<int:attempt_id>/", views.order_detail_view, name="order_detail"),
    path("orders/<int:attempt_id>/status-recheck/", views.order_status_recheck_view, name="order_status_recheck"),
    path("orders/<int:attempt_id>/fill-sync/", views.fill_sync_resync_view, name="fill_sync_resync"),
    path("active-locks/<int:active_lock_id>/manual-closeout/", views.active_lock_closeout_view, name="active_lock_closeout"),
    path("account-overview/", views.account_overview_view, name="account_overview"),
    path("account-overview/refresh/", views.account_overview_refresh_view, name="account_overview_refresh"),
    path("runtime-guard/issues/", views.runtime_guard_issues_view, name="runtime_guard_issues"),
    path("runtime-guard/issues/<int:issue_id>/", views.runtime_guard_issue_detail_view, name="runtime_guard_issue_detail"),
    path("runtime-guard/issues/<int:issue_id>/status/", views.runtime_guard_issue_status_view, name="runtime_guard_issue_status"),
    path("alerts/", views.alerts_view, name="alerts"),
    path("alerts/<int:alert_id>/", views.alert_detail_view, name="alert_detail"),
    path("real-trading/", views.real_trading_view, name="real_trading"),
    path("audit-log/", views.audit_log_view, name="audit_log"),
    path("performance/", views.performance_records_view, name="performance_records"),
    path("performance/<int:performance_id>/", views.performance_record_detail_view, name="performance_record_detail"),
    path("performance/preview/", views.performance_preview_view, name="performance_preview"),
    path("performance/backfill/", views.performance_backfill_view, name="performance_backfill"),
    path("ai-review/", views.ai_review_requests_view, name="ai_review_requests"),
    path("ai-review/<int:request_id>/", views.ai_review_request_detail_view, name="ai_review_request_detail"),
    path("ai-review/create/", views.ai_review_create_request_view, name="ai_review_create_request"),
    path("ai-review/<int:request_id>/build-package/", views.ai_review_build_package_view, name="ai_review_build_package"),
    path("ai-review/<int:request_id>/run/", views.ai_review_run_view, name="ai_review_run"),
    path("ai-review/suggestions/<int:suggestion_id>/status/", views.ai_review_update_suggestion_view, name="ai_review_update_suggestion"),
]
