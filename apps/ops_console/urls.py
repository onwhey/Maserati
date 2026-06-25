"""OpsConsole 模块：后端查询 API 路由；不承载业务逻辑，不访问外部服务，不涉及交易执行。"""

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
    path("account-overview/", views.account_overview_view, name="account_overview"),
    path("runtime-guard/issues/", views.runtime_guard_issues_view, name="runtime_guard_issues"),
    path("runtime-guard/issues/<int:issue_id>/", views.runtime_guard_issue_detail_view, name="runtime_guard_issue_detail"),
    path("alerts/", views.alerts_view, name="alerts"),
    path("alerts/<int:alert_id>/", views.alert_detail_view, name="alert_detail"),
    path("real-trading/", views.real_trading_view, name="real_trading"),
    path("audit-log/", views.audit_log_view, name="audit_log"),
    path("performance/", views.performance_records_view, name="performance_records"),
    path("performance/<int:performance_id>/", views.performance_record_detail_view, name="performance_record_detail"),
    path("performance/preview/", views.performance_preview_view, name="performance_preview"),
    path("performance/backfill/", views.performance_backfill_view, name="performance_backfill"),
]
