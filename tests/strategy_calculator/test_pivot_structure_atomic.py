from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from apps.strategy_calculator.atomic_signal import PivotStructureAtomicCalculator
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType


def _feature(value: Any, *, value_type: str = "decimal", feature_value_id: int = 1) -> dict[str, Any]:
    return {"feature_value_id": feature_value_id, "value": value, "value_type": value_type}


def _zone_features(
    *,
    side: str,
    timeframe: str = "1d",
    window: int = 365,
    lower: str | None = "71500",
    upper: str | None = "72800",
    core: str | None = "72150",
    strength: str = "0.80",
    status: str = "active",
    distance_pct: str | None = "0.010",
    distance_atr: str | None = "0.5",
    start_id: int = 1,
) -> dict[str, Any]:
    suffix = f"{timeframe}_{window}"
    prefix = f"structure_pivot_{side}"
    return {
        f"{prefix}_lower_{suffix}": _feature(lower, feature_value_id=start_id),
        f"{prefix}_upper_{suffix}": _feature(upper, feature_value_id=start_id + 1),
        f"{prefix}_core_{suffix}": _feature(core, feature_value_id=start_id + 2),
        f"{prefix}_strength_{suffix}": _feature(strength, feature_value_id=start_id + 3),
        f"{prefix}_status_{suffix}": _feature(status, value_type="text", feature_value_id=start_id + 4),
        f"structure_pivot_distance_to_{side}_pct_{suffix}": _feature(distance_pct, feature_value_id=start_id + 5),
        f"structure_pivot_distance_to_{side}_atr_{suffix}": _feature(distance_atr, feature_value_id=start_id + 6),
    }


def _calculate(*, params: dict[str, Any], feature_values: dict[str, Any], direction: str = "neutral"):
    calculator = PivotStructureAtomicCalculator()
    return calculator.calculate(
        CalculatorInput(
            calculator_type=CalculatorType.ATOMIC_SIGNAL,
            input_schema_version=calculator.metadata.input_schema_version,
            output_schema_version=calculator.metadata.output_schema_version,
            business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
            frozen_params=params,
            values={
                "signal_code": "test_signal",
                "default_direction": direction,
                "feature_values": feature_values,
            },
        )
    )


def test_pivot_structure_atomic_near_support_matches_when_distance_within_threshold() -> None:
    output = _calculate(
        params={
            "condition": "near",
            "level": "major",
            "timeframe": "1d",
            "window": 365,
            "side": "support",
            "near_threshold": "0.025",
            "label_zh": "1d 靠近拐点支撑",
        },
        feature_values=_zone_features(side="support", status="active", distance_pct="0.010"),
    )

    assert output.values["value"] is True
    assert output.values["direction"] == "neutral"
    assert output.values["strength"] == Decimal("1")
    assert "成立" in output.values["evidence_text_zh"]


def test_pivot_structure_atomic_support_holds_does_not_match_active_status_only() -> None:
    output = _calculate(
        params={
            "condition": "holds",
            "level": "major",
            "timeframe": "1d",
            "window": 365,
            "side": "support",
            "label_zh": "1d 拐点支撑守住",
        },
        feature_values=_zone_features(side="support", status="active", distance_pct="0.010"),
    )

    assert output.values["value"] is False
    assert output.values["direction"] == "neutral"
    assert output.values["strength"] == Decimal("0")


def test_pivot_structure_atomic_breakdown_confirmed_uses_bearish_direction() -> None:
    output = _calculate(
        params={
            "condition": "breakdown_confirmed",
            "level": "major",
            "timeframe": "1d",
            "window": 365,
            "side": "support",
            "label_zh": "1d 拐点支撑确认跌破",
        },
        feature_values=_zone_features(side="support", status="breakdown_confirmed", distance_pct="-0.030"),
        direction="bearish",
    )

    assert output.values["value"] is True
    assert output.values["direction"] == "bearish"


def test_pivot_structure_atomic_between_support_resistance_matches_when_price_is_between() -> None:
    support = _zone_features(
        side="support",
        lower="71500",
        upper="72800",
        core="72150",
        status="active",
        distance_pct="0.030",
        start_id=1,
    )
    resistance = _zone_features(
        side="resistance",
        lower="85000",
        upper="86500",
        core="85750",
        status="active",
        distance_pct="0.050",
        start_id=20,
    )
    output = _calculate(
        params={
            "condition": "between",
            "level": "major",
            "timeframe": "1d",
            "window": 365,
            "side": "both",
            "label_zh": "1d 拐点支撑压力夹层",
        },
        feature_values={**support, **resistance},
    )

    assert output.values["value"] is True
    assert "支撑有效=True" in output.evidence_items[0]["facts"]
    assert "压力有效=True" in output.evidence_items[0]["facts"]
