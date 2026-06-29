from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("execution", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordersubmissionattempt",
            name="time_in_force",
            field=models.CharField(blank=True, max_length=40, verbose_name="timeInForce"),
        ),
        migrations.AddField(
            model_name="ordersubmissionattempt",
            name="limit_price",
            field=models.DecimalField(blank=True, decimal_places=18, max_digits=38, null=True, verbose_name="LIMIT price"),
        ),
        migrations.AddField(
            model_name="ordersubmissionattempt",
            name="limit_valid_until_utc",
            field=models.DateTimeField(blank=True, null=True, verbose_name="LIMIT valid until UTC"),
        ),
        migrations.AddField(
            model_name="ordersubmissionattempt",
            name="price_condition_hash",
            field=models.CharField(blank=True, max_length=80, verbose_name="price condition hash"),
        ),
    ]
