"""为策略分析版本包增加数据库级唯一启用槽位。"""

from django.db import migrations, models


def populate_active_slot(apps, schema_editor):
    release_model = apps.get_model("strategy_analysis", "StrategyAnalysisRelease")
    active_rows = list(release_model.objects.filter(is_active=True).values("id", "approval_status"))
    if len(active_rows) > 1:
        raise RuntimeError("迁移前已存在多个启用中的 StrategyAnalysisRelease，请先人工处理")
    if active_rows:
        if active_rows[0]["approval_status"] != "approved":
            raise RuntimeError("迁移前启用中的 StrategyAnalysisRelease 不是 approved，请先人工处理")
        release_model.objects.filter(id=active_rows[0]["id"]).update(active_slot=1)


class Migration(migrations.Migration):
    dependencies = [
        ("strategy_analysis", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="strategyanalysisrelease",
            name="active_slot",
            field=models.PositiveSmallIntegerField(
                blank=True,
                editable=False,
                null=True,
                unique=True,
                verbose_name="唯一启用槽位",
            ),
        ),
        migrations.RunPython(populate_active_slot, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="strategyanalysisrelease",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("active_slot__isnull", True), ("is_active", False))
                    | models.Q(("active_slot", 1), ("approval_status", "approved"), ("is_active", True))
                ),
                name="valid_strategy_release_active_slot",
            ),
        ),
    ]
