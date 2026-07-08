"""StrategyAnalysis 模块：MarketRegime 市场环境分类目录。
负责：提供 MarketRegime code 的中文名、说明和展示顺序，供后台展示和路由配置读取。
不负责：计算 MarketRegimeSnapshot、选择策略、执行策略算法、生成目标仓位或订单动作。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.strategy_calculator.market_regime.context_structure_regime import REGIME_CODES


@dataclass(frozen=True)
class MarketRegimeCatalogItem:
    code: str
    display_name: str
    description: str
    sort_order: int


MARKET_REGIME_CATALOG: tuple[MarketRegimeCatalogItem, ...] = (
    MarketRegimeCatalogItem(
        code="bullish_trend_continuation",
        display_name="多头趋势延续",
        description="大背景和趋势同向偏多，行情处于顺势推进阶段。",
        sort_order=10,
    ),
    MarketRegimeCatalogItem(
        code="bullish_breakout",
        display_name="多头向上突破",
        description="价格向上突破关键结构，且突破行为具备延续条件。",
        sort_order=20,
    ),
    MarketRegimeCatalogItem(
        code="bullish_pullback",
        display_name="多头回调",
        description="大背景偏多，但短周期正在回调或修复，尚未破坏多头结构。",
        sort_order=30,
    ),
    MarketRegimeCatalogItem(
        code="bullish_high_range",
        display_name="多头高位震荡",
        description="多头背景仍在，但价格处于高位区间震荡，方向延续不够明确。",
        sort_order=40,
    ),
    MarketRegimeCatalogItem(
        code="bearish_trend_continuation",
        display_name="空头趋势延续",
        description="大背景和趋势同向偏空，行情处于顺势下跌阶段。",
        sort_order=50,
    ),
    MarketRegimeCatalogItem(
        code="bearish_breakdown",
        display_name="空头向下跌破",
        description="价格向下跌破关键结构，且跌破行为具备延续条件。",
        sort_order=60,
    ),
    MarketRegimeCatalogItem(
        code="bearish_rebound",
        display_name="空头反弹",
        description="大背景偏空，但短周期正在反弹或修复，尚未破坏空头结构。",
        sort_order=70,
    ),
    MarketRegimeCatalogItem(
        code="bearish_low_range",
        display_name="空头低位震荡",
        description="空头背景仍在，但价格处于低位区间震荡，方向延续不够明确。",
        sort_order=80,
    ),
    MarketRegimeCatalogItem(
        code="bullish_top_reversal_candidate",
        display_name="多头高位结构受压",
        description="多头或高位背景下结构开始受压，但不等于顶部已经确认。",
        sort_order=90,
    ),
    MarketRegimeCatalogItem(
        code="bearish_bottom_reversal_candidate",
        display_name="空头低位结构受压",
        description="空头或低位背景下结构开始受到修复压力，但不等于底部已经确认。",
        sort_order=100,
    ),
    MarketRegimeCatalogItem(
        code="neutral_range",
        display_name="无方向震荡",
        description="市场缺少明确方向优势，价格主要处于无方向震荡环境。",
        sort_order=110,
    ),
    MarketRegimeCatalogItem(
        code="high_risk_environment",
        display_name="高风险环境",
        description="市场风险或信号失真风险较高，普通策略不应主动承担方向风险。",
        sort_order=120,
    ),
    MarketRegimeCatalogItem(
        code="unclear_environment",
        display_name="不明确环境",
        description="现有事实不足以形成可靠市场环境判断。",
        sort_order=130,
    ),
)

_CATALOG_BY_CODE = {item.code: item for item in MARKET_REGIME_CATALOG}

if set(_CATALOG_BY_CODE) != set(REGIME_CODES):
    missing = sorted(set(REGIME_CODES) - set(_CATALOG_BY_CODE))
    extra = sorted(set(_CATALOG_BY_CODE) - set(REGIME_CODES))
    raise RuntimeError(f"MarketRegime catalog 与算法输出不一致：missing={missing}, extra={extra}")


def list_market_regime_catalog() -> tuple[MarketRegimeCatalogItem, ...]:
    return MARKET_REGIME_CATALOG


def get_market_regime_catalog_item(code: str) -> MarketRegimeCatalogItem | None:
    return _CATALOG_BY_CODE.get(str(code or "").strip())


def market_regime_display_name(code: str, fallback: str = "") -> str:
    item = get_market_regime_catalog_item(code)
    if item is None:
        return fallback or str(code or "").strip()
    return item.display_name


def market_regime_description(code: str, fallback: str = "") -> str:
    item = get_market_regime_catalog_item(code)
    if item is None:
        return fallback
    return item.description


def regime_codes_from_match_conditions(match_conditions: dict[str, Any]) -> tuple[str, ...]:
    raw_codes = match_conditions.get("regime_codes") if isinstance(match_conditions, dict) else None
    if not isinstance(raw_codes, list):
        return ()
    return tuple(str(code).strip() for code in raw_codes if str(code or "").strip())


def market_regime_display_name_from_match_conditions(
    match_conditions: dict[str, Any],
    *,
    fallback: str = "",
) -> str:
    regime_codes = regime_codes_from_match_conditions(match_conditions)
    if not regime_codes:
        return fallback
    names = [market_regime_display_name(code) for code in regime_codes]
    return " / ".join(name for name in names if name) or fallback


def market_regime_description_from_match_conditions(match_conditions: dict[str, Any]) -> str:
    regime_codes = regime_codes_from_match_conditions(match_conditions)
    descriptions = [market_regime_description(code) for code in regime_codes]
    return " / ".join(description for description in descriptions if description)
