"""RiskCheck 模块：维护 rule_code 到插件的注册关系；不读写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import RiskRulePlugin


@dataclass
class RiskRuleRegistry:
    _plugins: dict[str, RiskRulePlugin] = field(default_factory=dict)

    def register(self, plugin: RiskRulePlugin) -> None:
        if plugin.rule_code in self._plugins:
            raise ValueError(f"重复注册 RiskRulePlugin：{plugin.rule_code}")
        self._plugins[plugin.rule_code] = plugin

    def get(self, rule_code: str) -> RiskRulePlugin | None:
        return self._plugins.get(rule_code)

    def registered_rule_codes(self) -> set[str]:
        return set(self._plugins)


def default_registry() -> RiskRuleRegistry:
    from .rules import BUILTIN_PLUGINS

    registry = RiskRuleRegistry()
    for plugin in BUILTIN_PLUGINS:
        registry.register(plugin)
    return registry
