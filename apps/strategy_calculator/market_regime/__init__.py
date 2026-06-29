"""MarketRegime 计算器包：提供市场环境分类算法；不读写数据库，不访问 Redis，不访问外部服务，不涉及交易执行。"""

from .context_structure_regime import ContextStructureRegimeCalculator

__all__ = ["ContextStructureRegimeCalculator"]
