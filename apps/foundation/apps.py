from django.apps import AppConfig


class FoundationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.foundation"
    verbose_name = "项目底座"

    def ready(self) -> None:
        from . import checks  # noqa: F401

