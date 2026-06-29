"""OpsConsole 模块：后端查询与受控人工操作 API 路由；不承载业务逻辑，不直接访问外部服务，不提交订单。"""

from __future__ import annotations

from django.urls import path

from . import views


app_name = "ops_console"

urlpatterns = [
    path("auth/login/", views.auth_login_view, name="auth_login"),
    path("auth/logout/", views.auth_logout_view, name="auth_logout"),
    path("auth/me/", views.auth_me_view, name="auth_me"),
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
    path("review-datasets/records/", views.review_dataset_records_view, name="review_dataset_records"),
    path("review-datasets/records/<int:record_id>/", views.review_dataset_record_detail_view, name="review_dataset_record_detail"),
    path("review-datasets/exports/", views.review_dataset_exports_view, name="review_dataset_exports"),
    path("review-datasets/exports/<int:export_id>/", views.review_dataset_export_detail_view, name="review_dataset_export_detail"),
    path("review-datasets/preview/", views.review_dataset_preview_view, name="review_dataset_preview"),
    path("review-datasets/exports/create/", views.review_dataset_export_create_view, name="review_dataset_export_create"),
    path("review-datasets/exports/<int:export_id>/download-mark/", views.review_dataset_export_download_mark_view, name="review_dataset_export_download_mark"),
]
