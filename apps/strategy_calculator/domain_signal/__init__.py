"""DomainSignal calculator 集合；仅执行纯计算，不读写存储或访问外部服务。"""

from .single_atomic_passthrough import SingleAtomicPassthroughCalculator

__all__ = ["SingleAtomicPassthroughCalculator"]
