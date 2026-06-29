"""ReviewDataset 模块：注册后置复盘数据集 app，不承载业务逻辑。"""

from __future__ import annotations

from django.apps import AppConfig


class ReviewDatasetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.review_dataset"
