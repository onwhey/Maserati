"""移除 MySQL 不支持的检查约束状态；唯一启用槽位继续提供数据库唯一性。"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("strategy_analysis", "0002_release_active_slot"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="strategyanalysisrelease",
            name="valid_strategy_release_active_slot",
        ),
    ]
