from django.apps import AppConfig


class RuntimeConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.runtime_config"
    verbose_name = "运行配置"

