"""RiskCheck 模块：注册 Django app；不读写数据库；不访问外部服务；不涉及交易执行。"""

from django.apps import AppConfig


class RiskCheckConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk_check"
    verbose_name = "RiskCheck 风控审批"
