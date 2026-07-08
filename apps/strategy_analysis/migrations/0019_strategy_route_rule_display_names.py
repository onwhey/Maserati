from django.db import migrations


REGIME_DISPLAY_NAMES = {
    "bullish_trend_continuation": "多头趋势延续",
    "bullish_breakout": "多头向上突破",
    "bullish_pullback": "多头回调",
    "bullish_high_range": "多头高位震荡",
    "bearish_trend_continuation": "空头趋势延续",
    "bearish_breakdown": "空头向下跌破",
    "bearish_rebound": "空头反弹",
    "bearish_low_range": "空头低位震荡",
    "bullish_top_reversal_candidate": "多头高位结构受压",
    "bearish_bottom_reversal_candidate": "空头低位结构受压",
    "neutral_range": "无方向震荡",
    "high_risk_environment": "高风险环境",
    "unclear_environment": "不明确环境",
}


def route_rule_display_name(match_conditions):
    if not isinstance(match_conditions, dict):
        return ""
    raw_codes = match_conditions.get("regime_codes")
    if not isinstance(raw_codes, list):
        return ""
    names = [
        f"{REGIME_DISPLAY_NAMES[code]}接线规则"
        for code in raw_codes
        if isinstance(code, str) and code in REGIME_DISPLAY_NAMES
    ]
    return " / ".join(names)


def forwards(apps, schema_editor):
    StrategyRouteRule = apps.get_model("strategy_analysis", "StrategyRouteRule")
    for rule in StrategyRouteRule.objects.all().only("id", "match_conditions"):
        display_name = route_rule_display_name(rule.match_conditions)
        if display_name:
            StrategyRouteRule.objects.filter(id=rule.id).update(display_name=display_name)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("strategy_analysis", "0018_strategy_backtest_period_analysis_detail"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
