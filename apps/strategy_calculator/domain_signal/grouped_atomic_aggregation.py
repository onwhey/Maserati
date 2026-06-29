"""DomainSignal 模块：按领域规则聚合同一组 AtomicSignalValue。
负责：纯计算 DomainSignalValue 所需方向、状态、强度、覆盖率、一致性和证据。
不负责：读写数据库、访问 Redis、访问外部服务、发送 Hermes、调用大模型、交易执行、真实交易。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class GroupedAtomicAggregationCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals/strategy_domain_design.md",
        implementation_document_path="docs/implementation/domain_signal/grouped_atomic_aggregation__1.0.0.md",
    )

    _DIRECTION_VALUES = {"bullish", "bearish", "neutral", "none"}

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        domain_code = values.get("domain_code")
        output_mode = values.get("output_mode")
        atomic_values = values.get("atomic_values")
        if not isinstance(domain_code, str) or not domain_code:
            return self._failed("domain_code_missing", "缺少领域代码")
        if not isinstance(output_mode, str) or not output_mode:
            return self._failed("domain_output_mode_missing", "缺少领域输出模式")
        if not isinstance(atomic_values, (list, tuple)):
            return self._failed("atomic_values_missing", "缺少原子信号输入")

        domain_type = str(params.get("domain_type") or domain_code)
        payload = self._prepare_payload(params=params, atomic_values=atomic_values)
        if payload.get("error_code"):
            return self._failed(str(payload["error_code"]), str(payload["error_message"]))

        if domain_type == "market_context":
            result = self._market_context(payload)
        elif domain_type == "trend":
            result = self._trend(payload)
        elif domain_type == "momentum":
            result = self._momentum(payload)
        elif domain_type == "volatility":
            result = self._volatility(payload)
        elif domain_type == "structure":
            result = self._structure(payload)
        elif domain_type == "risk_state":
            result = self._risk_state(payload)
        else:
            return self._failed("domain_type_unsupported", f"不支持的领域聚合类型：{domain_type}")
        if result.get("error_code"):
            return self._failed(str(result["error_code"]), str(result["error_message"]))

        direction = str(result["direction"])
        state_code = str(result["state_code"])
        if direction not in self._DIRECTION_VALUES:
            return self._failed("domain_direction_invalid", "领域方向不合法")
        strength = self._ratio(result.get("strength"), field_name="strength")
        agreement = self._ratio(result.get("agreement_ratio"), field_name="agreement_ratio", allow_none=True)
        coverage = payload["coverage_ratio"]
        evidence_item = {
            "evidence_type": "domain_grouped_atomic_aggregation",
            "domain_code": domain_code,
            "domain_type": domain_type,
            "direction": direction,
            "state_code": state_code,
            "strength": str(strength),
            "coverage_ratio": str(coverage),
            "agreement_ratio": str(agreement) if agreement is not None else None,
            "active_signal_codes": payload["active_signal_codes"],
            "counts": result.get("counts", {}),
            "state_tags": result.get("state_tags", []),
            "summary": result.get("summary", {}),
        }
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "direction": direction,
                "state_code": state_code,
                "strength": strength,
                "coverage_ratio": coverage,
                "agreement_ratio": agreement,
                "evidence_text_zh": str(result["evidence_text_zh"]),
            },
            evidence_items=(evidence_item,),
            calculation_summary={
                "domain_code": domain_code,
                "domain_type": domain_type,
                "state_code": state_code,
                "active_signal_count": len(payload["active_signal_codes"]),
            },
        )

    def _prepare_payload(self, *, params: Mapping[str, Any], atomic_values: Any) -> dict[str, Any]:
        allowed_codes = self._string_list(params.get("allowed_atomic_signal_codes"))
        if not allowed_codes:
            return {"error_code": "domain_allowed_atomic_empty", "error_message": "领域定义缺少允许原子信号"}
        values_by_code: dict[str, Mapping[str, Any]] = {}
        for item in atomic_values:
            if not isinstance(item, Mapping):
                return {"error_code": "atomic_value_invalid", "error_message": "原子信号输入必须是结构化映射"}
            code = item.get("signal_code")
            if not isinstance(code, str) or not code:
                return {"error_code": "atomic_signal_code_missing", "error_message": "原子信号输入缺少 signal_code"}
            values_by_code[code] = item
        active_codes = sorted(code for code, item in values_by_code.items() if self._is_active_atomic(item))
        active_set = set(active_codes)
        return {
            "params": params,
            "allowed_codes": allowed_codes,
            "values_by_code": values_by_code,
            "active_signal_codes": active_codes,
            "active_set": active_set,
            "coverage_ratio": Decimal(len(values_by_code)) / Decimal(len(allowed_codes)),
        }

    def _market_context(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        params = payload["params"]
        active = payload["active_set"]
        bullish_codes = self._string_list(params.get("bullish_group"))
        bearish_codes = self._string_list(params.get("bearish_group"))
        bullish_count = self._count(active, bullish_codes)
        bearish_count = self._count(active, bearish_codes)
        direction, gap = self._direction_from_counts(
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            minimum_gap=self._int_param(params, "min_direction_gap", 2),
        )
        state_tags = self._state_tags(active, params)
        state_code = self._state_from_tags(
            state_tags=state_tags,
            default_when_direction=direction,
            priority=self._string_list(params.get("state_priority")),
            prefix="market_context",
        )
        strength = Decimal("0") if direction == "neutral" else self._capped_ratio(gap, self._int_param(params, "strong_direction_gap", 4))
        agreement = self._agreement_from_counts(direction, bullish_count, bearish_count)
        return {
            "direction": direction,
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": agreement,
            "counts": {"bullish": bullish_count, "bearish": bearish_count, "direction_gap": gap},
            "state_tags": state_tags,
            "summary": {"state_priority": self._string_list(params.get("state_priority"))},
            "evidence_text_zh": (
                f"market_context 领域聚合完成：偏多证据 {bullish_count} 项，偏空证据 {bearish_count} 项，"
                f"方向为 {direction}，状态为 {state_code}。该结论只描述市场大背景，不生成交易动作。"
            ),
        }

    def _trend(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        params = payload["params"]
        active = payload["active_set"]
        primary_bull = self._count(active, self._string_list(params.get("primary_bullish_group")))
        primary_bear = self._count(active, self._string_list(params.get("primary_bearish_group")))
        short_bull = self._count(active, self._string_list(params.get("short_cycle_bullish_group")))
        short_bear = self._count(active, self._string_list(params.get("short_cycle_bearish_group")))
        primary_direction, primary_gap = self._direction_from_counts(
            bullish_count=primary_bull,
            bearish_count=primary_bear,
            minimum_gap=self._int_param(params, "primary_min_gap", 2),
        )
        short_direction, short_gap = self._direction_from_counts(
            bullish_count=short_bull,
            bearish_count=short_bear,
            minimum_gap=self._int_param(params, "short_cycle_min_gap", 2),
        )
        state_code = self._state_code_from_pair(
            params=params,
            primary_direction=primary_direction,
            short_direction=short_direction,
            default_code="trend_unclear",
        )
        strength = Decimal("0") if primary_direction == "neutral" else self._capped_ratio(
            primary_gap,
            self._int_param(params, "strong_primary_gap", 4),
        )
        agreement = self._agreement_from_counts(primary_direction, primary_bull, primary_bear)
        return {
            "direction": primary_direction,
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": agreement,
            "counts": {
                "primary_bullish": primary_bull,
                "primary_bearish": primary_bear,
                "short_cycle_bullish": short_bull,
                "short_cycle_bearish": short_bear,
                "primary_gap": primary_gap,
                "short_cycle_gap": short_gap,
            },
            "state_tags": [f"trend_primary_{primary_direction}", f"trend_short_cycle_{short_direction}"],
            "summary": {"primary_direction": primary_direction, "short_cycle_direction": short_direction},
            "evidence_text_zh": (
                f"trend 领域聚合完成：1d 主趋势为 {primary_direction}，4h 辅助状态为 {short_direction}，"
                f"状态为 {state_code}。4h 只作为辅助事实，不单独推翻 1d 主趋势。"
            ),
        }

    def _momentum(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        params = payload["params"]
        active = payload["active_set"]
        primary_bull = self._count(active, self._string_list(params.get("primary_bullish_group")))
        primary_bear = self._count(active, self._string_list(params.get("primary_bearish_group")))
        short_bull = self._count(active, self._string_list(params.get("short_cycle_bullish_group")))
        short_bear = self._count(active, self._string_list(params.get("short_cycle_bearish_group")))
        primary_direction, primary_gap = self._direction_from_counts(
            bullish_count=primary_bull,
            bearish_count=primary_bear,
            minimum_gap=self._int_param(params, "primary_min_gap", 2),
        )
        short_direction, _short_gap = self._direction_from_counts(
            bullish_count=short_bull,
            bearish_count=short_bear,
            minimum_gap=self._int_param(params, "short_cycle_min_gap", 2),
        )
        state_tags = self._state_tags(active, params)
        phase = self._momentum_phase(primary_direction=primary_direction, state_tags=state_tags)
        state_code = f"momentum_{primary_direction}_{phase}" if primary_direction != "neutral" else f"momentum_neutral_{phase}"
        strength = Decimal("0") if primary_direction == "neutral" else self._capped_ratio(
            primary_gap,
            self._int_param(params, "strong_primary_gap", 4),
        )
        agreement = self._agreement_from_counts(primary_direction, primary_bull, primary_bear)
        return {
            "direction": primary_direction,
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": agreement,
            "counts": {
                "primary_bullish": primary_bull,
                "primary_bearish": primary_bear,
                "short_cycle_bullish": short_bull,
                "short_cycle_bearish": short_bear,
            },
            "state_tags": [*state_tags, f"momentum_short_cycle_{short_direction}"],
            "summary": {"primary_direction": primary_direction, "phase": phase, "short_cycle_direction": short_direction},
            "evidence_text_zh": (
                f"momentum 领域聚合完成：1d 推动力方向为 {primary_direction}，阶段为 {phase}，"
                f"4h 推动力为 {short_direction}。该结论只描述动能状态，不生成交易动作。"
            ),
        }

    def _volatility(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        params = payload["params"]
        active = payload["active_set"]
        low_count = self._count(active, self._string_list(params.get("low_volatility_group")))
        high_count = self._count(active, self._string_list(params.get("high_volatility_group")))
        extreme_count = self._count(active, self._string_list(params.get("extreme_volatility_group")))
        compression_active = "volatility_4h_compression" in active
        expansion_active = "volatility_4h_expansion" in active
        low_min = self._int_param(params, "low_min_count", 2)
        high_min = self._int_param(params, "high_min_count", 2)
        if extreme_count >= self._int_param(params, "extreme_min_count", 1):
            state_code = "volatility_extreme"
            strength = Decimal("1")
        elif high_count >= high_min and low_count < low_min:
            state_code = "volatility_high"
            strength = self._capped_ratio(high_count, self._int_param(params, "strong_state_denominator", 4))
        elif low_count >= low_min and high_count < high_min and compression_active:
            state_code = "volatility_low_compression"
            strength = self._capped_ratio(low_count, self._int_param(params, "strong_state_denominator", 4))
        elif low_count >= low_min and high_count < high_min:
            state_code = "volatility_low"
            strength = self._capped_ratio(low_count, self._int_param(params, "strong_state_denominator", 4))
        elif low_count >= low_min and high_count >= high_min:
            state_code = "volatility_mixed"
            strength = Decimal("0.5")
        else:
            state_code = "volatility_normal"
            strength = Decimal("0")
        state_tags = self._state_tags(active, params)
        if compression_active:
            state_tags.append("volatility_compression_active")
        if expansion_active:
            state_tags.append("volatility_expansion_active")
        if low_count >= low_min and high_count >= high_min:
            state_tags.append("volatility_low_high_mixed")
        if extreme_count and low_count >= low_min:
            state_tags.append("volatility_extreme_with_low_volatility_conflict")
        return {
            "direction": "none",
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": Decimal("0"),
            "counts": {
                "low_volatility": low_count,
                "high_volatility": high_count,
                "extreme_volatility": extreme_count,
            },
            "state_tags": sorted(set(state_tags)),
            "summary": {"compression_active": compression_active, "expansion_active": expansion_active},
            "evidence_text_zh": (
                f"volatility 领域聚合完成：低波动证据 {low_count} 项，高波动证据 {high_count} 项，"
                f"极高波动证据 {extreme_count} 项，状态为 {state_code}。该结论只描述波动状态。"
            ),
        }

    def _structure(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        params = payload["params"]
        active = payload["active_set"]
        major_state = self._structure_state(active, prefix="major")
        minor_state = self._structure_state(active, prefix="minor")
        major_conflict = self._structure_conflict(active, prefix="major")
        minor_conflict = self._structure_conflict(active, prefix="minor")
        if major_conflict:
            return {"error_code": "structure_major_state_conflict", "error_message": "大结构互斥状态同时成立"}
        if minor_conflict:
            return {"error_code": "structure_minor_state_conflict", "error_message": "小结构互斥状态同时成立"}
        direction = "bullish" if major_state == "breakout_up" else "bearish" if major_state == "breakdown_down" else "neutral"
        state_code = self._structure_state_code(major_state=major_state, minor_state=minor_state)
        strength = self._structure_strength(major_state=major_state, minor_state=minor_state, params=params)
        agreement = Decimal("1") if self._structure_aligned(major_state=major_state, minor_state=minor_state) else Decimal("0")
        return {
            "direction": direction,
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": agreement,
            "counts": {"major_active": self._count_prefix(active, "structure_major_"), "minor_active": self._count_prefix(active, "structure_minor_")},
            "state_tags": [f"structure_major_{major_state}", f"structure_minor_{minor_state}"],
            "summary": {"major_structure": major_state, "minor_structure": minor_state},
            "evidence_text_zh": (
                f"structure 领域聚合完成：1d 大结构为 {major_state}，4h 小结构为 {minor_state}，"
                f"组合状态为 {state_code}。该结论只描述价格结构位置，不输出订单动作。"
            ),
        }

    def _risk_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        active = payload["active_set"]
        values_by_code = payload["values_by_code"]
        category_scores: dict[str, Decimal] = {
            "signal_reliability_risk": Decimal("0"),
            "long_exposure_risk": Decimal("0"),
            "short_exposure_risk": Decimal("0"),
            "long_chase_risk": Decimal("0"),
            "short_chase_risk": Decimal("0"),
            "market_disorder_risk": Decimal("0"),
        }
        risk_directions: set[str] = set()
        active_risks: list[dict[str, str]] = []
        for code in active:
            item = values_by_code.get(code, {})
            value_json = item.get("value_json")
            if not isinstance(value_json, Mapping):
                continue
            category = str(value_json.get("risk_category") or "")
            direction = str(value_json.get("risk_direction") or "")
            severity = str(value_json.get("risk_severity") or "none")
            score = Decimal("1") if severity == "high" else Decimal("0.55") if severity == "elevated" else Decimal("0")
            if category in category_scores and score > category_scores[category]:
                category_scores[category] = score
            if direction:
                risk_directions.add(direction)
            active_risks.append({"signal_code": code, "risk_category": category, "risk_direction": direction, "risk_severity": severity})
        signal_score = max(category_scores["signal_reliability_risk"], category_scores["market_disorder_risk"])
        high_unreliable = signal_score >= Decimal("0.70")
        elevated_categories = [category for category, score in category_scores.items() if score >= Decimal("0.55")]
        unclear = (
            category_scores["long_exposure_risk"] >= Decimal("0.55")
            and category_scores["short_exposure_risk"] >= Decimal("0.55")
            and signal_score < Decimal("0.55")
        ) or (
            category_scores["long_chase_risk"] >= Decimal("0.55")
            and category_scores["short_chase_risk"] >= Decimal("0.55")
        ) or (len(elevated_categories) >= 3 and not high_unreliable)
        if high_unreliable:
            state_code = "risk_high_signal_unreliable"
        elif unclear:
            state_code = "risk_unclear"
        elif elevated_categories:
            state_code = "risk_elevated_classifiable"
        else:
            state_code = "risk_clear"
        strength = max(category_scores.values()) if category_scores else Decimal("0")
        return {
            "direction": "none",
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": Decimal("0"),
            "counts": {category: str(score) for category, score in category_scores.items()},
            "state_tags": sorted(elevated_categories),
            "summary": {"risk_directions": sorted(risk_directions), "active_risks": active_risks},
            "evidence_text_zh": (
                f"risk_state 领域聚合完成：风险状态为 {state_code}，主要风险类别为 {','.join(elevated_categories) or '无'}。"
                "该结论只描述市场风险事实，不等于停止交易、减仓或下单。"
            ),
        }

    @staticmethod
    def _failed(error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=GroupedAtomicAggregationCalculator.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item) for item in value if str(item).strip()]

    @staticmethod
    def _is_active_atomic(item: Mapping[str, Any]) -> bool:
        if item.get("is_valid") is not True:
            return False
        if item.get("value_bool") is True:
            return True
        value_json = item.get("value_json")
        return isinstance(value_json, Mapping) and value_json.get("condition_met") is True

    @staticmethod
    def _count(active: set[str], codes: list[str]) -> int:
        return sum(1 for code in codes if code in active)

    @staticmethod
    def _count_prefix(active: set[str], prefix: str) -> int:
        return sum(1 for code in active if code.startswith(prefix))

    @staticmethod
    def _int_param(params: Mapping[str, Any], key: str, default: int) -> int:
        try:
            return max(1, int(params.get(key, default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _direction_from_counts(*, bullish_count: int, bearish_count: int, minimum_gap: int) -> tuple[str, int]:
        gap = abs(bullish_count - bearish_count)
        if gap < minimum_gap:
            return "neutral", gap
        return ("bullish" if bullish_count > bearish_count else "bearish"), gap

    @staticmethod
    def _agreement_from_counts(direction: str, bullish_count: int, bearish_count: int) -> Decimal:
        total = bullish_count + bearish_count
        if total == 0 or direction == "neutral":
            return Decimal("0")
        supporting = bullish_count if direction == "bullish" else bearish_count
        return Decimal(supporting) / Decimal(total)

    @staticmethod
    def _capped_ratio(numerator: int, denominator: int) -> Decimal:
        return min(Decimal("1"), Decimal(numerator) / Decimal(max(1, denominator)))

    @staticmethod
    def _ratio(value: Any, *, field_name: str, allow_none: bool = False) -> Decimal | None:
        if value is None:
            if allow_none:
                return None
            raise ValueError(f"{field_name} is required")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} invalid") from exc
        if not result.is_finite() or result < 0 or result > 1:
            raise ValueError(f"{field_name} must be 0..1")
        return result

    def _state_tags(self, active: set[str], params: Mapping[str, Any]) -> list[str]:
        mapping = params.get("state_signals")
        if not isinstance(mapping, Mapping):
            return []
        return sorted({str(tag) for code, tag in mapping.items() if str(code) in active and str(tag).strip()})

    @staticmethod
    def _state_from_tags(*, state_tags: list[str], default_when_direction: str, priority: list[str], prefix: str) -> str:
        for tag in priority:
            if tag in state_tags:
                return f"{prefix}_{tag}"
        if default_when_direction in {"bullish", "bearish"}:
            return f"{prefix}_{default_when_direction}"
        return f"{prefix}_neutral"

    @staticmethod
    def _state_code_from_pair(
        *,
        params: Mapping[str, Any],
        primary_direction: str,
        short_direction: str,
        default_code: str,
    ) -> str:
        mapping = params.get("state_code_map")
        if not isinstance(mapping, Mapping):
            return default_code
        return str(mapping.get(f"{primary_direction}:{short_direction}") or default_code)

    @staticmethod
    def _momentum_phase(*, primary_direction: str, state_tags: list[str]) -> str:
        if primary_direction == "bullish":
            if "bullish_exhausting" in state_tags:
                return "exhausting"
            if "movement_efficiency_low" in state_tags:
                return "choppy"
            if "bullish_strengthening" in state_tags:
                return "strengthening"
            return "present"
        if primary_direction == "bearish":
            if "bearish_exhausting" in state_tags:
                return "exhausting"
            if "movement_efficiency_low" in state_tags:
                return "choppy"
            if "bearish_strengthening" in state_tags:
                return "strengthening"
            return "present"
        if "movement_efficiency_low" in state_tags:
            return "choppy"
        return "unclear"

    @staticmethod
    def _structure_conflict(active: set[str], *, prefix: str) -> bool:
        up = f"structure_{prefix}_breakout_up" in active
        down = f"structure_{prefix}_breakdown_down" in active
        support = f"structure_{prefix}_near_support" in active
        resistance = f"structure_{prefix}_near_resistance" in active
        return (up and down) or (support and resistance)

    @staticmethod
    def _structure_state(active: set[str], *, prefix: str) -> str:
        order = (
            ("breakdown_down", f"structure_{prefix}_breakdown_down"),
            ("breakout_up", f"structure_{prefix}_breakout_up"),
            ("unclear", f"structure_{prefix}_unclear"),
            ("near_support", f"structure_{prefix}_near_support"),
            ("near_resistance", f"structure_{prefix}_near_resistance"),
            ("range_middle", f"structure_{prefix}_range_middle"),
            ("lower_half", f"structure_{prefix}_lower_half"),
            ("upper_half", f"structure_{prefix}_upper_half"),
        )
        for state, code in order:
            if code in active:
                return state
        valid = (
            f"structure_{prefix}_range_valid" in active
            or f"structure_{prefix}_support_valid" in active
            or f"structure_{prefix}_resistance_valid" in active
        )
        return "range_observed" if valid else "unclear"

    @staticmethod
    def _structure_state_code(*, major_state: str, minor_state: str) -> str:
        if major_state in {"breakout_up", "breakdown_down"}:
            return f"structure_major_{major_state}"
        if major_state == "near_support" and minor_state == "near_support":
            return "structure_major_near_support_minor_aligned"
        if major_state == "near_support" and minor_state == "breakdown_down":
            return "structure_major_near_support_minor_breakdown"
        if major_state == "near_resistance" and minor_state == "near_resistance":
            return "structure_major_near_resistance_minor_aligned"
        if major_state == "near_resistance" and minor_state == "breakout_up":
            return "structure_major_near_resistance_minor_breakout"
        if major_state == "range_middle" and minor_state == "near_support":
            return "structure_major_range_middle_minor_near_support"
        if major_state == "range_middle" and minor_state == "near_resistance":
            return "structure_major_range_middle_minor_near_resistance"
        if major_state == "unclear" and minor_state not in {"unclear", "range_observed"}:
            return "structure_major_unclear_minor_clear"
        if major_state == "unclear" and minor_state == "unclear":
            return "structure_unclear"
        return f"structure_major_{major_state}_minor_{minor_state}"

    def _structure_strength(self, *, major_state: str, minor_state: str, params: Mapping[str, Any]) -> Decimal:
        if major_state in {"breakout_up", "breakdown_down"}:
            strength = Decimal("0.90")
        elif major_state in {"near_support", "near_resistance"}:
            strength = Decimal(str(params.get("clear_state_strength", "0.80")))
        elif major_state in {"range_middle", "lower_half", "upper_half", "range_observed"}:
            strength = Decimal("0.55")
        elif minor_state not in {"unclear", "range_observed"}:
            strength = Decimal(str(params.get("minor_only_strength_cap", "0.50")))
        else:
            strength = Decimal(str(params.get("unclear_strength", "0")))
        if self._structure_aligned(major_state=major_state, minor_state=minor_state):
            strength = min(Decimal("1"), strength + Decimal("0.10"))
        return max(Decimal("0"), min(Decimal("1"), strength))

    @staticmethod
    def _structure_aligned(*, major_state: str, minor_state: str) -> bool:
        if major_state == minor_state and major_state not in {"unclear", "range_observed"}:
            return True
        return (major_state, minor_state) in {
            ("near_support", "lower_half"),
            ("near_resistance", "upper_half"),
            ("range_middle", "range_middle"),
            ("breakout_up", "breakout_up"),
            ("breakdown_down", "breakdown_down"),
        }
