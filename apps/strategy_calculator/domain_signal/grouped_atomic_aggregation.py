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
    _OPTIONAL_EVIDENCE_BLOCK_ATOMICS = {
        "structure_historical_major_reference": frozenset(
            {
                "structure_historical_major_zone_valid",
                "structure_historical_major_near_zone",
                "structure_historical_major_support_like",
                "structure_historical_major_resistance_like",
                "structure_historical_major_role_flip_candidate",
                "structure_historical_major_far_from_zone",
            }
        ),
    }

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
        if domain_type == "structure":
            self._append_structure_historical_evidence(result)

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
        configured_allowed_codes = self._string_list(params.get("allowed_atomic_signal_codes"))
        if not configured_allowed_codes:
            return {"error_code": "domain_allowed_atomic_empty", "error_message": "领域定义缺少允许原子信号"}
        values_by_code: dict[str, Mapping[str, Any]] = {}
        for item in atomic_values:
            if not isinstance(item, Mapping):
                return {"error_code": "atomic_value_invalid", "error_message": "原子信号输入必须是结构化映射"}
            code = item.get("signal_code")
            if not isinstance(code, str) or not code:
                return {"error_code": "atomic_signal_code_missing", "error_message": "原子信号输入缺少 signal_code"}
            values_by_code[code] = item
        runtime_allowed_codes = [code for code in configured_allowed_codes if code in values_by_code]
        if not runtime_allowed_codes:
            return {"error_code": "domain_runtime_allowed_atomic_empty", "error_message": "当前版本包没有可参与该领域的原子信号"}
        active_codes = sorted(code for code, item in values_by_code.items() if self._is_active_atomic(item))
        active_set = set(active_codes)
        return {
            "params": params,
            "allowed_codes": runtime_allowed_codes,
            "values_by_code": values_by_code,
            "active_signal_codes": active_codes,
            "active_set": active_set,
            "coverage_ratio": Decimal(len(values_by_code)) / Decimal(len(runtime_allowed_codes)),
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
            major_state = "conflicted"
        if minor_conflict:
            minor_state = "conflicted"
        direction = "bullish" if major_state == "breakout_up" else "bearish" if major_state == "breakdown_down" else "neutral"
        state_code = self._structure_state_code(major_state=major_state, minor_state=minor_state)
        strength = self._structure_strength(major_state=major_state, minor_state=minor_state, params=params)
        agreement = Decimal("1") if self._structure_aligned(major_state=major_state, minor_state=minor_state) else Decimal("0")
        zone_summary = self._structure_zone_summary(
            values_by_code=payload["values_by_code"],
            major_state=major_state,
            minor_state=minor_state,
        )
        structure_evidence = self._structure_evidence_summary(
            active=active,
            major_state=major_state,
            minor_state=minor_state,
        )
        historical_major_reference = self._structure_optional_evidence_block(
            block_code="structure_historical_major_reference",
            values_by_code=payload["values_by_code"],
        )
        optional_summary = {}
        if historical_major_reference is not None:
            optional_summary["historical_major_reference"] = historical_major_reference
        return {
            "direction": direction,
            "state_code": state_code,
            "strength": strength,
            "agreement_ratio": agreement,
            "counts": {
                "major_active": self._count_prefix(active, "structure_major_"),
                "minor_active": self._count_prefix(active, "structure_minor_"),
                "major_conflict": major_conflict,
                "minor_conflict": minor_conflict,
            },
            "state_tags": self._structure_state_tags(
                major_state=major_state,
                minor_state=minor_state,
                major_conflict=major_conflict,
                minor_conflict=minor_conflict,
            ),
            "summary": {
                "major_structure": major_state,
                "minor_structure": minor_state,
                "major_conflict": major_conflict,
                "minor_conflict": minor_conflict,
                "structure_evidence": structure_evidence,
                **zone_summary,
                **optional_summary,
            },
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
        up = f"structure_{prefix}_breakout_up" in active or f"structure_{prefix}_resistance_breakout_candidate" in active
        down = f"structure_{prefix}_breakdown_down" in active or f"structure_{prefix}_support_breakdown_candidate" in active
        support = f"structure_{prefix}_near_support" in active
        resistance = f"structure_{prefix}_near_resistance" in active
        return (up and down) or (support and resistance)

    @staticmethod
    def _structure_state(active: set[str], *, prefix: str) -> str:
        order = (
            ("breakdown_down", f"structure_{prefix}_support_breakdown_confirmed"),
            ("breakout_up", f"structure_{prefix}_resistance_breakout_confirmed"),
            ("breakdown_down", f"structure_{prefix}_support_breakdown_candidate"),
            ("breakout_up", f"structure_{prefix}_resistance_breakout_candidate"),
            ("breakdown_down", f"structure_{prefix}_breakdown_down"),
            ("breakout_up", f"structure_{prefix}_breakout_up"),
            ("unclear", f"structure_{prefix}_unclear"),
            ("near_support", f"structure_{prefix}_support_holds"),
            ("near_resistance", f"structure_{prefix}_resistance_holds"),
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
        if major_state == "conflicted" and minor_state == "conflicted":
            return "structure_conflicted"
        if major_state == "conflicted":
            return "structure_major_conflicted"
        if minor_state == "conflicted":
            return f"structure_major_{major_state}_minor_conflicted"
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
        if major_state == "conflicted":
            strength = Decimal(str(params.get("unclear_strength", "0")))
        elif major_state in {"breakout_up", "breakdown_down"}:
            strength = Decimal("0.90")
        elif major_state in {"near_support", "near_resistance"}:
            strength = Decimal(str(params.get("clear_state_strength", "0.80")))
        elif major_state in {"range_middle", "lower_half", "upper_half", "range_observed"}:
            strength = Decimal("0.55")
        elif minor_state not in {"unclear", "range_observed", "conflicted"}:
            strength = Decimal(str(params.get("minor_only_strength_cap", "0.50")))
        else:
            strength = Decimal(str(params.get("unclear_strength", "0")))
        if self._structure_aligned(major_state=major_state, minor_state=minor_state):
            strength = min(Decimal("1"), strength + Decimal("0.10"))
        return max(Decimal("0"), min(Decimal("1"), strength))

    def _structure_zone_summary(
        self,
        *,
        values_by_code: Mapping[str, Mapping[str, Any]],
        major_state: str,
        minor_state: str,
    ) -> dict[str, Any]:
        feature_values = self._structure_feature_values(values_by_code)
        major_support = self._structure_zone(
            feature_values,
            lower_code="structure_major_support_lower_1d_365",
            upper_code="structure_major_support_upper_1d_365",
        )
        major_resistance = self._structure_zone(
            feature_values,
            lower_code="structure_major_resistance_lower_1d_365",
            upper_code="structure_major_resistance_upper_1d_365",
        )
        minor_support = self._structure_zone(
            feature_values,
            lower_code="structure_minor_support_lower_4h_120",
            upper_code="structure_minor_support_upper_4h_120",
        )
        minor_resistance = self._structure_zone(
            feature_values,
            lower_code="structure_minor_resistance_lower_4h_120",
            upper_code="structure_minor_resistance_upper_4h_120",
        )
        summary: dict[str, Any] = {
            "current_zone_position": self._structure_current_zone_position(
                major_state=major_state,
                minor_state=minor_state,
            ),
        }
        optional_values = {
            "major_support_zone": major_support,
            "major_resistance_zone": major_resistance,
            "minor_support_zone": minor_support,
            "minor_resistance_zone": minor_resistance,
            "support_zone": self._preferred_structure_zone(
                zone_kind="support",
                major_state=major_state,
                minor_state=minor_state,
                major_zone=major_support,
                minor_zone=minor_support,
            ),
            "resistance_zone": self._preferred_structure_zone(
                zone_kind="resistance",
                major_state=major_state,
                minor_state=minor_state,
                major_zone=major_resistance,
                minor_zone=minor_resistance,
            ),
        }
        summary.update({key: value for key, value in optional_values.items() if value is not None})
        return summary

    def _structure_evidence_summary(
        self,
        *,
        active: set[str],
        major_state: str,
        minor_state: str,
    ) -> dict[str, Any]:
        major = self._structure_level_evidence(active=active, prefix="major", label_zh="1d 大结构")
        minor = self._structure_level_evidence(active=active, prefix="minor", label_zh="4h 小结构")
        facts_zh = [
            text
            for text in (
                *self._structure_level_fact_texts(major),
                *self._structure_level_fact_texts(minor),
            )
            if text
        ]
        primary_state_zh = self._structure_primary_state_zh(major_state=major_state, minor_state=minor_state)
        return {
            "major": major,
            "minor": minor,
            "primary_state_zh": primary_state_zh,
            "facts_zh": facts_zh,
        }

    @staticmethod
    def _structure_level_evidence(*, active: set[str], prefix: str, label_zh: str) -> dict[str, Any]:
        support_valid = f"structure_{prefix}_support_valid" in active
        resistance_valid = f"structure_{prefix}_resistance_valid" in active
        near_support = f"structure_{prefix}_near_support" in active
        near_resistance = f"structure_{prefix}_near_resistance" in active
        support_holds = f"structure_{prefix}_support_holds" in active or (support_valid and near_support)
        resistance_holds = f"structure_{prefix}_resistance_holds" in active or (resistance_valid and near_resistance)
        breakout_up = f"structure_{prefix}_breakout_up" in active or f"structure_{prefix}_resistance_breakout_candidate" in active
        breakdown_down = f"structure_{prefix}_breakdown_down" in active or f"structure_{prefix}_support_breakdown_candidate" in active
        support_breakdown_confirmed = f"structure_{prefix}_support_breakdown_confirmed" in active
        resistance_breakout_confirmed = f"structure_{prefix}_resistance_breakout_confirmed" in active
        range_valid = f"structure_{prefix}_range_valid" in active
        return {
            "label_zh": label_zh,
            "support_valid": support_valid,
            "resistance_valid": resistance_valid,
            "near_support": near_support,
            "near_resistance": near_resistance,
            "range_valid": range_valid,
            "support_holds": support_holds and not breakdown_down,
            "resistance_holds": resistance_holds and not breakout_up,
            "support_breakdown_candidate": breakdown_down,
            "resistance_breakout_candidate": breakout_up,
            "support_breakdown_confirmed": support_breakdown_confirmed,
            "resistance_breakout_confirmed": resistance_breakout_confirmed,
            "breakout_up": breakout_up,
            "breakdown_down": breakdown_down,
        }

    @staticmethod
    def _structure_level_fact_texts(evidence: Mapping[str, Any]) -> list[str]:
        label = str(evidence.get("label_zh") or "结构")
        facts: list[str] = []
        if evidence.get("support_holds"):
            facts.append(f"{label}支撑仍有效")
        if evidence.get("resistance_holds"):
            facts.append(f"{label}压力仍有效")
        if evidence.get("support_breakdown_candidate"):
            facts.append(f"{label}支撑跌破候选")
        if evidence.get("resistance_breakout_candidate"):
            facts.append(f"{label}压力突破候选")
        if evidence.get("range_valid") and not facts:
            facts.append(f"{label}支撑压力区间可解释")
        return facts

    @staticmethod
    def _structure_primary_state_zh(*, major_state: str, minor_state: str) -> str:
        if major_state == "conflicted" or minor_state == "conflicted":
            return "结构证据冲突"
        if major_state == "breakdown_down":
            return "大结构支撑跌破候选"
        if major_state == "breakout_up":
            return "大结构压力突破候选"
        if major_state == "near_support":
            return "大结构靠近支撑"
        if major_state == "near_resistance":
            return "大结构靠近压力"
        if minor_state == "breakdown_down":
            return "小结构支撑跌破候选"
        if minor_state == "breakout_up":
            return "小结构压力突破候选"
        if minor_state == "near_support":
            return "小结构靠近支撑"
        if minor_state == "near_resistance":
            return "小结构靠近压力"
        if major_state in {"range_middle", "lower_half", "upper_half", "range_observed"}:
            return "大结构区间位置明确"
        return "结构证据不足"

    def _structure_optional_evidence_block(
        self,
        *,
        block_code: str,
        values_by_code: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        if not self._optional_evidence_block_selected(block_code=block_code, values_by_code=values_by_code):
            return None
        if block_code == "structure_historical_major_reference":
            return self._structure_historical_major_reference(values_by_code=values_by_code)
        return None

    def _structure_historical_major_reference(
        self,
        *,
        values_by_code: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        feature_values = self._structure_feature_values(values_by_code)
        zone = self._structure_zone(
            feature_values,
            lower_code="structure_historical_major_zone_lower_1d_720",
            upper_code="structure_historical_major_zone_upper_1d_720",
        )
        zone_valid = self._atomic_condition_met(values_by_code, "structure_historical_major_zone_valid")
        near_zone = self._atomic_condition_met(values_by_code, "structure_historical_major_near_zone")
        far_from_zone = self._atomic_condition_met(values_by_code, "structure_historical_major_far_from_zone")
        support_like = self._atomic_condition_met(values_by_code, "structure_historical_major_support_like")
        resistance_like = self._atomic_condition_met(values_by_code, "structure_historical_major_resistance_like")
        role_flip_candidate = self._atomic_condition_met(
            values_by_code,
            "structure_historical_major_role_flip_candidate",
        )
        role = str(feature_values.get("structure_historical_major_zone_role_1d_720") or "").strip()
        if not role:
            if role_flip_candidate:
                role = "role_flip_candidate"
            elif support_like:
                role = "support_like"
            elif resistance_like:
                role = "resistance_like"
            else:
                role = "unclear"

        is_valid = bool(zone_valid and zone)
        reference = {
            "is_valid": is_valid,
            "reason_code": "" if is_valid else "historical_major_reference_invalid_or_missing",
            "zone": zone,
            "origin_type": self._optional_text(feature_values.get("structure_historical_major_zone_origin_type_1d_720")),
            "role": role,
            "role_zh": self._structure_historical_role_zh(role),
            "distance_to_zone_pct": self._optional_text(
                feature_values.get("structure_historical_major_distance_to_zone_pct_1d_720")
            ),
            "covered_bars": self._optional_text(feature_values.get("structure_historical_major_zone_covered_bars_1d_720")),
            "test_count": self._optional_text(feature_values.get("structure_historical_major_zone_test_count_1d_720")),
            "last_reaction_at_utc": self._optional_text(
                feature_values.get("structure_historical_major_zone_last_reaction_at_utc_1d_720")
            ),
            "last_reaction_pct": self._optional_text(
                feature_values.get("structure_historical_major_zone_last_reaction_pct_1d_720")
            ),
            "is_near": bool(near_zone),
            "is_far": bool(far_from_zone),
            "is_role_flip_candidate": bool(role_flip_candidate),
        }
        reference["summary_zh"] = self._structure_historical_summary_zh(reference)
        reference["should_mention_in_evidence"] = bool(
            is_valid and (reference["is_near"] or reference["is_role_flip_candidate"])
        )
        return reference

    @staticmethod
    def _atomic_condition_met(values_by_code: Mapping[str, Mapping[str, Any]], signal_code: str) -> bool:
        item = values_by_code.get(signal_code)
        return isinstance(item, Mapping) and GroupedAtomicAggregationCalculator._is_active_atomic(item)

    @classmethod
    def _optional_evidence_block_selected(
        cls,
        *,
        block_code: str,
        values_by_code: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        signal_codes = cls._OPTIONAL_EVIDENCE_BLOCK_ATOMICS.get(block_code, frozenset())
        return any(signal_code in values_by_code for signal_code in signal_codes)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _structure_historical_role_zh(role: str) -> str:
        mapping = {
            "support_like": "更像长周期支撑",
            "resistance_like": "更像长周期压力",
            "role_flip_candidate": "支撑压力角色互换观察位",
            "unclear": "角色不明确",
        }
        return mapping.get(role, "角色不明确")

    @staticmethod
    def _structure_historical_summary_zh(reference: Mapping[str, Any]) -> str:
        if not reference.get("is_valid"):
            return "未识别到有效的 720 天历史大结构参考位。"
        role_zh = str(reference.get("role_zh") or "角色不明确")
        if reference.get("is_role_flip_candidate"):
            return (
                f"当前价格处在 720 天历史大结构参考位附近，{role_zh}；"
                "该事实只提示长周期支撑压力可能发生角色互换，不生成交易动作。"
            )
        if reference.get("is_near"):
            return (
                f"当前价格接近 720 天历史大结构参考位，该区域{role_zh}；"
                "该事实只作为价格结构参考，不生成交易动作。"
            )
        if reference.get("is_far"):
            return (
                f"存在有效的 720 天历史大结构参考位，该区域{role_zh}，但当前价格明显远离该区域；"
                "当前周期只作远端背景参考。"
            )
        return (
            f"存在有效的 720 天历史大结构参考位，该区域{role_zh}；"
            "当前周期只作结构背景参考。"
        )

    @staticmethod
    def _append_structure_historical_evidence(result: dict[str, Any]) -> None:
        summary = result.get("summary")
        if not isinstance(summary, Mapping):
            return
        reference = summary.get("historical_major_reference")
        if not isinstance(reference, Mapping) or not reference.get("should_mention_in_evidence"):
            return
        summary_text = str(reference.get("summary_zh") or "").strip()
        if not summary_text:
            return
        result["evidence_text_zh"] = f"{str(result.get('evidence_text_zh') or '').strip()} {summary_text}".strip()

    @staticmethod
    def _structure_feature_values(values_by_code: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in values_by_code.values():
            value_json = item.get("value_json")
            if not isinstance(value_json, Mapping):
                continue
            feature_values = value_json.get("feature_values")
            if not isinstance(feature_values, Mapping):
                continue
            for code, feature_payload in feature_values.items():
                if not isinstance(feature_payload, Mapping):
                    continue
                code_text = str(code).strip()
                if code_text and code_text not in result:
                    result[code_text] = feature_payload.get("value")
        return result

    @staticmethod
    def _structure_zone(
        feature_values: Mapping[str, Any],
        *,
        lower_code: str,
        upper_code: str,
    ) -> dict[str, str] | None:
        lower = feature_values.get(lower_code)
        upper = feature_values.get(upper_code)
        if lower is None or upper is None:
            return None
        try:
            lower_decimal = Decimal(str(lower))
            upper_decimal = Decimal(str(upper))
        except (InvalidOperation, ValueError):
            return None
        if not lower_decimal.is_finite() or not upper_decimal.is_finite() or lower_decimal > upper_decimal:
            return None
        return {"lower": str(lower), "upper": str(upper)}

    @staticmethod
    def _preferred_structure_zone(
        *,
        zone_kind: str,
        major_state: str,
        minor_state: str,
        major_zone: dict[str, str] | None,
        minor_zone: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if zone_kind == "support":
            if major_state in {"near_support", "breakdown_down"}:
                return major_zone or minor_zone
            if minor_state in {"near_support", "breakdown_down"}:
                return minor_zone or major_zone
            return major_zone or minor_zone
        if zone_kind == "resistance":
            if major_state in {"near_resistance", "breakout_up"}:
                return major_zone or minor_zone
            if minor_state in {"near_resistance", "breakout_up"}:
                return minor_zone or major_zone
            return major_zone or minor_zone
        return major_zone or minor_zone

    @staticmethod
    def _structure_current_zone_position(*, major_state: str, minor_state: str) -> str:
        if major_state == "conflicted" or minor_state == "conflicted":
            return "conflicted"
        if major_state in {"near_support", "near_resistance", "breakout_up", "breakdown_down"}:
            return major_state
        if minor_state in {"near_support", "near_resistance", "breakout_up", "breakdown_down"}:
            return f"minor_{minor_state}"
        return major_state

    @staticmethod
    def _structure_aligned(*, major_state: str, minor_state: str) -> bool:
        if major_state == minor_state and major_state not in {"unclear", "range_observed", "conflicted"}:
            return True
        return (major_state, minor_state) in {
            ("near_support", "lower_half"),
            ("near_resistance", "upper_half"),
            ("range_middle", "range_middle"),
            ("breakout_up", "breakout_up"),
            ("breakdown_down", "breakdown_down"),
        }

    @staticmethod
    def _structure_state_tags(
        *,
        major_state: str,
        minor_state: str,
        major_conflict: bool,
        minor_conflict: bool,
    ) -> list[str]:
        tags = [f"structure_major_{major_state}", f"structure_minor_{minor_state}"]
        if major_conflict:
            tags.append("structure_major_state_conflict_detected")
        if minor_conflict:
            tags.append("structure_minor_state_conflict_detected")
        return tags


class GroupedAtomicAggregationV11Calculator(GroupedAtomicAggregationCalculator):
    """Structure 1.1 使用的领域聚合计算器版本别名；逻辑与 1.0 一致，仅区分定义版本语义。"""

    metadata = CalculatorMetadata(
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.1.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals/structure_domain_signals_v1.md",
        implementation_document_path="docs/implementation/domain_signal/grouped_atomic_aggregation__1.0.0.md",
    )


class GroupedAtomicAggregationV2Calculator(GroupedAtomicAggregationCalculator):
    """Structure 2.0 使用的领域聚合计算器；补充支撑/压力穿透与确认语义，不生成交易动作。"""

    metadata = CalculatorMetadata(
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="2.0.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals/structure_domain_signals_v2.md",
        implementation_document_path="docs/implementation/domain_signal/grouped_atomic_aggregation__1.0.0.md",
    )

    def _structure(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(super()._structure(payload))
        active = payload["active_set"]
        legacy_state_code = str(result.get("state_code") or "")
        semantic = self._structure_v2_semantic_state(active=active, legacy_state_code=legacy_state_code)
        support_resistance_context = self._structure_v2_support_resistance_context(active=active)

        result["direction"] = semantic["direction"]
        result["state_code"] = semantic["state_code"]
        result["strength"] = max(Decimal(str(result.get("strength") or "0")), Decimal(str(semantic["strength"])))
        result["agreement_ratio"] = Decimal(str(semantic["agreement_ratio"]))
        result["state_tags"] = sorted(set([*result.get("state_tags", []), *semantic["state_tags"]]))
        summary = dict(result.get("summary") or {})
        summary["legacy_state_code"] = legacy_state_code
        summary["structure_state_v2"] = semantic
        summary["support_resistance_context"] = support_resistance_context
        result["summary"] = summary
        context_text = str(support_resistance_context.get("text_zh") or "")
        result["evidence_text_zh"] = (
            f"structure v2 领域聚合完成：结构状态为 {semantic['state_zh']}。"
            f"{semantic['reason_zh']}{context_text}该结论只描述支撑压力结构事实，不输出交易动作。"
        )
        return result

    @staticmethod
    def _structure_v2_support_resistance_context(*, active: set[str]) -> dict[str, Any]:
        major_support_holds = "structure_major_support_holds" in active
        major_resistance_holds = "structure_major_resistance_holds" in active
        minor_support_holds = "structure_minor_support_holds" in active
        minor_resistance_holds = "structure_minor_resistance_holds" in active
        major_support_resistance_conflict = major_support_holds and major_resistance_holds
        minor_support_resistance_conflict = minor_support_holds and minor_resistance_holds
        any_support_resistance_conflict = major_support_resistance_conflict or minor_support_resistance_conflict

        active_context_signal_codes = [
            signal_code
            for signal_code, enabled in (
                ("structure_major_support_holds", major_support_holds),
                ("structure_major_resistance_holds", major_resistance_holds),
                ("structure_minor_support_holds", minor_support_holds),
                ("structure_minor_resistance_holds", minor_resistance_holds),
            )
            if enabled
        ]

        text_parts: list[str] = []
        if major_support_resistance_conflict:
            text_parts.append("1d 大支撑和 1d 大压力同时有效")
        elif major_support_holds:
            text_parts.append("1d 大支撑有效")
        elif major_resistance_holds:
            text_parts.append("1d 大压力有效")

        if minor_support_resistance_conflict:
            text_parts.append("4h 小支撑和 4h 小压力同时有效")
        elif minor_support_holds:
            text_parts.append("4h 小支撑有效")
        elif minor_resistance_holds:
            text_parts.append("4h 小压力有效")

        if not text_parts:
            text_zh = ""
        elif any_support_resistance_conflict:
            text_zh = f"补充事实：{'；'.join(text_parts)}，当前 Structure 不是单边结构。"
        else:
            text_zh = f"补充事实：{'；'.join(text_parts)}。"

        return {
            "has_major_support": major_support_holds,
            "has_major_resistance": major_resistance_holds,
            "has_minor_support": minor_support_holds,
            "has_minor_resistance": minor_resistance_holds,
            "major_support_resistance_conflict": major_support_resistance_conflict,
            "minor_support_resistance_conflict": minor_support_resistance_conflict,
            "any_support_resistance_conflict": any_support_resistance_conflict,
            "active_context_signal_codes": active_context_signal_codes,
            "closer_side": "unknown",
            "text_zh": text_zh,
        }

    @classmethod
    def _structure_v2_semantic_state(cls, *, active: set[str], legacy_state_code: str) -> dict[str, Any]:
        checks = (
            ("structure_major_support_breakdown_confirmed", "bearish", "structure_major_support_breakdown_confirmed", "1d 大支撑确认跌破", "1d 大支撑跌破幅度达到确认阈值，结构破坏证据较强。", "0.90", "1"),
            ("structure_major_resistance_breakout_confirmed", "bullish", "structure_major_resistance_breakout_confirmed", "1d 大压力确认突破", "1d 大压力突破幅度达到确认阈值，结构修复或延续证据较强。", "0.90", "1"),
            ("structure_major_support_breakdown_candidate", "bearish", "structure_major_support_breakdown_candidate", "1d 大支撑跌破候选", "1d 大支撑刚被跌破，但仍缺少收回、反抽失败等跨周期确认。", "0.75", "1"),
            ("structure_major_resistance_breakout_candidate", "bullish", "structure_major_resistance_breakout_candidate", "1d 大压力突破候选", "1d 大压力刚被突破，但仍缺少回踩有效等跨周期确认。", "0.75", "1"),
            ("structure_major_support_holds", "neutral", "structure_major_support_holds", "1d 大支撑守住", "价格靠近 1d 大支撑且仍收在支撑区上方，支撑暂未失效。", "0.65", "0"),
            ("structure_major_resistance_holds", "neutral", "structure_major_resistance_holds", "1d 大压力压住", "价格靠近 1d 大压力且仍收在压力区下方，压力暂未失效。", "0.65", "0"),
            ("structure_minor_support_breakdown_confirmed", "bearish", "structure_minor_support_breakdown_confirmed", "4h 小支撑确认跌破", "4h 小支撑跌破幅度达到确认阈值，但不能单独推翻 1d 大结构。", "0.55", "1"),
            ("structure_minor_resistance_breakout_confirmed", "bullish", "structure_minor_resistance_breakout_confirmed", "4h 小压力确认突破", "4h 小压力突破幅度达到确认阈值，但不能单独推翻 1d 大结构。", "0.55", "1"),
            ("structure_minor_support_breakdown_candidate", "bearish", "structure_minor_support_breakdown_candidate", "4h 小支撑跌破候选", "4h 小支撑刚被跌破，只表达短周期结构变化。", "0.45", "1"),
            ("structure_minor_resistance_breakout_candidate", "bullish", "structure_minor_resistance_breakout_candidate", "4h 小压力突破候选", "4h 小压力刚被突破，只表达短周期结构变化。", "0.45", "1"),
            ("structure_minor_support_holds", "neutral", "structure_minor_support_holds", "4h 小支撑守住", "价格靠近 4h 小支撑且仍收在支撑区上方。", "0.40", "0"),
            ("structure_minor_resistance_holds", "neutral", "structure_minor_resistance_holds", "4h 小压力压住", "价格靠近 4h 小压力且仍收在压力区下方。", "0.40", "0"),
        )
        for signal_code, direction, state_code, state_zh, reason_zh, strength, agreement in checks:
            if signal_code in active:
                return {
                    "state_code": state_code,
                    "state_zh": state_zh,
                    "direction": direction,
                    "strength": strength,
                    "agreement_ratio": agreement,
                    "reason_zh": reason_zh,
                    "trigger_signal_code": signal_code,
                    "legacy_state_code": legacy_state_code,
                    "state_tags": [state_code, f"{state_code}_active"],
                    "limitations": [
                        "第一版 Structure v2 尚未使用跨周期收回、反抽失败或回踩有效证据；确认状态主要基于突破/跌破幅度阈值。"
                    ],
                }
        return {
            "state_code": f"{legacy_state_code}_v2_observed" if legacy_state_code else "structure_v2_observed",
            "state_zh": "结构位置观察",
            "direction": "neutral",
            "strength": "0.35",
            "agreement_ratio": "0",
            "reason_zh": "当前未触发支撑守住、压力压住、跌破候选或突破候选等 Structure v2 语义。",
            "trigger_signal_code": "",
            "legacy_state_code": legacy_state_code,
            "state_tags": ["structure_v2_no_semantic_trigger"],
            "limitations": [
                "第一版 Structure v2 尚未使用跨周期收回、反抽失败或回踩有效证据；确认状态主要基于突破/跌破幅度阈值。"
            ],
        }


class GroupedAtomicAggregationV3Calculator(GroupedAtomicAggregationCalculator):
    """Structure 3.0 使用的领域聚合计算器；只聚合拐点型支撑压力原子事实，不生成交易动作。"""

    metadata = CalculatorMetadata(
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="3.0.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals/structure_domain_signals_v3.md",
        implementation_document_path="docs/implementation/domain_signal/grouped_atomic_aggregation__1.0.0.md",
    )

    _PIVOT_LEVEL_LABEL_ZH = {
        "major": "1d 大结构",
        "minor": "4h 小结构",
    }
    _PIVOT_LEVEL_SUFFIX = {
        "major": ("1d", "365"),
        "minor": ("4h", "120"),
    }
    _PIVOT_STATE_ZH = {
        "support_breakdown_confirmed": "确认跌破支撑",
        "resistance_breakout_confirmed": "确认突破压力",
        "support_breakdown_candidate": "支撑跌破候选",
        "resistance_breakout_candidate": "压力突破候选",
        "between_support_resistance": "处于支撑压力夹层",
        "support_holds": "支撑守住",
        "resistance_holds": "压力压住",
        "support_testing": "正在测试支撑",
        "resistance_testing": "正在测试压力",
        "near_support": "靠近支撑",
        "near_resistance": "靠近压力",
        "conflicted": "结构证据冲突",
        "unclear": "结构不明确",
    }

    def _structure(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        active = payload["active_set"]
        values_by_code = payload["values_by_code"]
        major = self._pivot_level_evidence(active=active, values_by_code=values_by_code, level="major")
        minor = self._pivot_level_evidence(active=active, values_by_code=values_by_code, level="minor")
        decision = self._pivot_domain_state(major=major, minor=minor)
        support_zone = self._preferred_pivot_zone(major=major, minor=minor, side="support")
        resistance_zone = self._preferred_pivot_zone(major=major, minor=minor, side="resistance")
        structure_evidence = {
            "major": major,
            "minor": minor,
            "primary_state_zh": decision["state_zh"],
            "facts_zh": [*major["facts_zh"], *minor["facts_zh"]],
        }
        current_zone_position = self._pivot_current_zone_position(major_state=major["state"], minor_state=minor["state"])
        return {
            "direction": decision["direction"],
            "state_code": decision["state_code"],
            "strength": decision["strength"],
            "agreement_ratio": decision["agreement_ratio"],
            "counts": {
                "major_active": self._count_prefix(active, "structure_pivot_major_"),
                "minor_active": self._count_prefix(active, "structure_pivot_minor_"),
                "major_state": major["state"],
                "minor_state": minor["state"],
            },
            "state_tags": sorted(
                set(
                    [
                        decision["state_code"],
                        f"structure_pivot_major_{major['state']}",
                        f"structure_pivot_minor_{minor['state']}",
                        *major["state_tags"],
                        *minor["state_tags"],
                    ]
                )
            ),
            "summary": {
                "major_structure": major["state"],
                "minor_structure": minor["state"],
                "structure_evidence": structure_evidence,
                "current_zone_position": current_zone_position,
                "major_support_zone": major.get("support_zone"),
                "major_resistance_zone": major.get("resistance_zone"),
                "minor_support_zone": minor.get("support_zone"),
                "minor_resistance_zone": minor.get("resistance_zone"),
                "support_zone": support_zone,
                "resistance_zone": resistance_zone,
            },
            "evidence_text_zh": (
                f"Structure v3 聚合完成：{major['label_zh']}为{major['state_zh']}，"
                f"{minor['label_zh']}为{minor['state_zh']}，最终结构状态为{decision['state_zh']}。"
                "该结论只描述拐点支撑压力事实，不生成交易动作。"
            ),
        }

    @classmethod
    def _pivot_level_evidence(
        cls,
        *,
        active: set[str],
        values_by_code: Mapping[str, Mapping[str, Any]],
        level: str,
    ) -> dict[str, Any]:
        prefix = f"structure_pivot_{level}"
        flags = {
            "support_valid": f"{prefix}_support_valid" in active,
            "near_support": f"{prefix}_near_support" in active,
            "support_testing": f"{prefix}_support_testing" in active,
            "support_holds": f"{prefix}_support_holds" in active,
            "support_breakdown_candidate": f"{prefix}_support_breakdown_candidate" in active,
            "support_breakdown_confirmed": f"{prefix}_support_breakdown_confirmed" in active,
            "resistance_valid": f"{prefix}_resistance_valid" in active,
            "near_resistance": f"{prefix}_near_resistance" in active,
            "resistance_testing": f"{prefix}_resistance_testing" in active,
            "resistance_holds": f"{prefix}_resistance_holds" in active,
            "resistance_breakout_candidate": f"{prefix}_resistance_breakout_candidate" in active,
            "resistance_breakout_confirmed": f"{prefix}_resistance_breakout_confirmed" in active,
            "between_support_resistance": f"{prefix}_between_support_resistance" in active,
            "unclear": f"{prefix}_unclear" in active,
        }
        state = cls._pivot_level_state(flags)
        state_zh = cls._PIVOT_STATE_ZH[state]
        support_zone = cls._pivot_zone(values_by_code=values_by_code, level=level, side="support")
        resistance_zone = cls._pivot_zone(values_by_code=values_by_code, level=level, side="resistance")
        facts_zh = cls._pivot_fact_texts(level=level, flags=flags, state_zh=state_zh)
        return {
            "label_zh": cls._PIVOT_LEVEL_LABEL_ZH[level],
            "state": state,
            "state_zh": state_zh,
            "support_zone": support_zone,
            "resistance_zone": resistance_zone,
            "state_tags": [f"{key}_active" for key, value in flags.items() if value],
            "facts_zh": facts_zh,
            **flags,
        }

    @classmethod
    def _pivot_level_state(cls, flags: Mapping[str, bool]) -> str:
        breakdown = flags["support_breakdown_confirmed"] or flags["support_breakdown_candidate"]
        breakout = flags["resistance_breakout_confirmed"] or flags["resistance_breakout_candidate"]
        if breakdown and breakout:
            return "conflicted"
        if flags["support_breakdown_confirmed"]:
            return "support_breakdown_confirmed"
        if flags["resistance_breakout_confirmed"]:
            return "resistance_breakout_confirmed"
        if flags["support_breakdown_candidate"]:
            return "support_breakdown_candidate"
        if flags["resistance_breakout_candidate"]:
            return "resistance_breakout_candidate"
        if flags["between_support_resistance"] or (flags["support_holds"] and flags["resistance_holds"]):
            return "between_support_resistance"
        if flags["support_holds"]:
            return "support_holds"
        if flags["resistance_holds"]:
            return "resistance_holds"
        if flags["support_testing"]:
            return "support_testing"
        if flags["resistance_testing"]:
            return "resistance_testing"
        if flags["near_support"]:
            return "near_support"
        if flags["near_resistance"]:
            return "near_resistance"
        return "unclear"

    @classmethod
    def _pivot_domain_state(cls, *, major: Mapping[str, Any], minor: Mapping[str, Any]) -> dict[str, Any]:
        major_state = str(major["state"])
        minor_state = str(minor["state"])
        state_code = cls._pivot_state_code(major_state=major_state, minor_state=minor_state)
        state_zh = cls._PIVOT_STATE_ZH.get(major_state, "结构不明确")
        if major_state == "support_breakdown_confirmed":
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=state_zh,
                direction="bearish",
                strength=Decimal("0.85"),
                agreement_ratio=Decimal("1"),
            )
        if major_state == "resistance_breakout_confirmed":
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=state_zh,
                direction="bullish",
                strength=Decimal("0.85"),
                agreement_ratio=Decimal("1"),
            )
        if major_state in {"support_breakdown_candidate", "resistance_breakout_candidate"}:
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=state_zh,
                direction="neutral",
                strength=Decimal("0.65"),
                agreement_ratio=Decimal("0"),
            )
        if major_state not in {"unclear", "conflicted"}:
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=state_zh,
                direction="neutral",
                strength=Decimal("0.55"),
                agreement_ratio=Decimal("0"),
            )
        if minor_state == "support_breakdown_confirmed":
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=f"大结构不明确，小结构{cls._PIVOT_STATE_ZH[minor_state]}",
                direction="bearish",
                strength=Decimal("0.45"),
                agreement_ratio=Decimal("1"),
            )
        if minor_state == "resistance_breakout_confirmed":
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=f"大结构不明确，小结构{cls._PIVOT_STATE_ZH[minor_state]}",
                direction="bullish",
                strength=Decimal("0.45"),
                agreement_ratio=Decimal("1"),
            )
        if minor_state not in {"unclear", "conflicted"}:
            return cls._pivot_state_result(
                state_code=state_code,
                state_zh=f"大结构不明确，小结构{cls._PIVOT_STATE_ZH[minor_state]}",
                direction="neutral",
                strength=Decimal("0.35"),
                agreement_ratio=Decimal("0"),
            )
        return cls._pivot_state_result(
            state_code=state_code,
            state_zh="结构不明确",
            direction="neutral",
            strength=Decimal("0"),
            agreement_ratio=Decimal("0"),
        )

    @staticmethod
    def _pivot_state_result(
        *,
        state_code: str,
        state_zh: str,
        direction: str,
        strength: Decimal,
        agreement_ratio: Decimal,
    ) -> dict[str, Any]:
        return {
            "state_code": state_code,
            "state_zh": state_zh,
            "direction": direction,
            "strength": strength,
            "agreement_ratio": agreement_ratio,
        }

    @staticmethod
    def _pivot_state_code(*, major_state: str, minor_state: str) -> str:
        if major_state == "conflicted":
            return "structure_pivot_major_conflicted"
        if major_state != "unclear":
            return f"structure_pivot_major_{major_state}"
        if minor_state == "conflicted":
            return "structure_pivot_major_unclear_minor_conflicted"
        if minor_state != "unclear":
            return f"structure_pivot_major_unclear_minor_{minor_state}"
        return "structure_pivot_unclear"

    @classmethod
    def _pivot_fact_texts(cls, *, level: str, flags: Mapping[str, bool], state_zh: str) -> list[str]:
        label = cls._PIVOT_LEVEL_LABEL_ZH[level]
        facts: list[str] = []
        if flags["between_support_resistance"] or (flags["support_holds"] and flags["resistance_holds"]):
            facts.append(f"{label}同时存在有效支撑和有效压力，当前处于夹层")
        elif flags["support_holds"]:
            facts.append(f"{label}支撑暂时守住")
        elif flags["resistance_holds"]:
            facts.append(f"{label}压力暂时压住")
        elif flags["support_testing"]:
            facts.append(f"{label}正在测试支撑")
        elif flags["resistance_testing"]:
            facts.append(f"{label}正在测试压力")
        elif flags["near_support"]:
            facts.append(f"{label}靠近支撑")
        elif flags["near_resistance"]:
            facts.append(f"{label}靠近压力")
        if flags["support_breakdown_candidate"]:
            facts.append(f"{label}出现支撑跌破候选")
        if flags["support_breakdown_confirmed"]:
            facts.append(f"{label}确认跌破支撑")
        if flags["resistance_breakout_candidate"]:
            facts.append(f"{label}出现压力突破候选")
        if flags["resistance_breakout_confirmed"]:
            facts.append(f"{label}确认突破压力")
        if not facts and flags["unclear"]:
            facts.append(f"{label}结构不明确")
        if not facts:
            facts.append(f"{label}未形成可用结构事实")
        if state_zh not in facts[-1]:
            facts.append(f"{label}最终状态：{state_zh}")
        return facts

    @staticmethod
    def _preferred_pivot_zone(
        *,
        major: Mapping[str, Any],
        minor: Mapping[str, Any],
        side: str,
    ) -> dict[str, str] | None:
        key = f"{side}_zone"
        major_state = str(major["state"])
        minor_state = str(minor["state"])
        if side == "support":
            states = {
                "support_holds",
                "support_testing",
                "near_support",
                "support_breakdown_candidate",
                "support_breakdown_confirmed",
                "between_support_resistance",
            }
        else:
            states = {
                "resistance_holds",
                "resistance_testing",
                "near_resistance",
                "resistance_breakout_candidate",
                "resistance_breakout_confirmed",
                "between_support_resistance",
            }
        if major_state in states:
            return major.get(key) or minor.get(key)
        if minor_state in states:
            return minor.get(key) or major.get(key)
        return major.get(key) or minor.get(key)

    @staticmethod
    def _pivot_current_zone_position(*, major_state: str, minor_state: str) -> str:
        states = {major_state, minor_state}
        if "conflicted" in states:
            return "conflicted"
        if "between_support_resistance" in states:
            return "between_support_resistance"
        if states & {"support_holds", "support_testing", "near_support", "support_breakdown_candidate", "support_breakdown_confirmed"}:
            return "near_or_below_support"
        if states & {
            "resistance_holds",
            "resistance_testing",
            "near_resistance",
            "resistance_breakout_candidate",
            "resistance_breakout_confirmed",
        }:
            return "near_or_above_resistance"
        return "unclear"

    @classmethod
    def _pivot_zone(
        cls,
        *,
        values_by_code: Mapping[str, Mapping[str, Any]],
        level: str,
        side: str,
    ) -> dict[str, str] | None:
        feature_values = cls._pivot_feature_values(values_by_code)
        timeframe, window = cls._PIVOT_LEVEL_SUFFIX[level]
        suffix = f"{timeframe}_{window}"
        prefix = f"structure_pivot_{side}"
        fields = {
            "lower": f"{prefix}_lower_{suffix}",
            "upper": f"{prefix}_upper_{suffix}",
            "core": f"{prefix}_core_{suffix}",
            "strength": f"{prefix}_strength_{suffix}",
            "status": f"{prefix}_status_{suffix}",
            "distance_pct": f"structure_pivot_distance_to_{side}_pct_{suffix}",
            "distance_atr": f"structure_pivot_distance_to_{side}_atr_{suffix}",
        }
        lower = feature_values.get(fields["lower"])
        upper = feature_values.get(fields["upper"])
        if lower is None or upper is None:
            return None
        result = {"lower": str(lower), "upper": str(upper)}
        for key in ("core", "strength", "status", "distance_pct", "distance_atr"):
            value = feature_values.get(fields[key])
            if value is not None:
                result[key] = str(value)
        return result

    @staticmethod
    def _pivot_feature_values(values_by_code: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in values_by_code.values():
            value_json = item.get("value_json")
            if isinstance(value_json, Mapping):
                feature_values = value_json.get("feature_values")
                if isinstance(feature_values, Mapping):
                    for code, payload in feature_values.items():
                        if isinstance(payload, Mapping) and str(code) not in result:
                            result[str(code)] = payload.get("value")
            evidence_items = item.get("evidence_items")
            if not isinstance(evidence_items, (list, tuple)):
                continue
            for evidence in evidence_items:
                if not isinstance(evidence, Mapping):
                    continue
                used_features = evidence.get("used_features")
                if not isinstance(used_features, (list, tuple)):
                    continue
                for feature in used_features:
                    if not isinstance(feature, Mapping):
                        continue
                    code = str(feature.get("feature_code") or "")
                    if code and code not in result and feature.get("missing") is not True:
                        result[code] = feature.get("observed_value")
        return result
