export type StrategyComponentLayer = {
  slug: string;
  title: string;
  description: string;
  componentTypes: string[];
};

export const strategyComponentLayers: StrategyComponentLayer[] = [
  {
    slug: "features",
    title: "特征",
    description: "选择 FeatureDefinition 的具体版本；Feature 不单独启用，是否进入发布包由已纳入原子信号反推。",
    componentTypes: ["feature_definition"]
  },
  {
    slug: "atomic-signals",
    title: "原子信号",
    description: "从原子层开始选择是否纳入当前策略组合；原子信号依赖的特征版本必须已选择。",
    componentTypes: ["atomic_signal_definition"]
  },
  {
    slug: "domain-signals",
    title: "领域信号",
    description: "管理领域层定义版本和纳入状态；领域对原子的依赖分为必需和可选。",
    componentTypes: ["domain_signal_definition"]
  },
  {
    slug: "market-regime",
    title: "市场环境",
    description: "管理 MarketRegime 定义版本和纳入状态；市场环境只识别行情状态，不生成订单动作。",
    componentTypes: ["market_regime_definition"]
  },
  {
    slug: "strategy-routing",
    title: "策略路由",
    description: "管理策略路由策略和路由规则；路由只选择策略，不执行策略算法。",
    componentTypes: ["strategy_route_policy", "strategy_route_rule"]
  },
  {
    slug: "strategies",
    title: "策略",
    description: "管理 StrategyDefinition 的具体算法版本和纳入状态。",
    componentTypes: ["strategy_definition"]
  },
  {
    slug: "signal-quality",
    title: "策略信号质量",
    description: "管理策略信号质量规则集；质量层只判断信号是否具备下游消费条件。",
    componentTypes: ["strategy_signal_quality_rule_set"]
  },
  {
    slug: "decision-policies",
    title: "目标仓位决策",
    description: "管理 DecisionPolicyDefinition；目标仓位决策只把策略信号映射为目标仓位语义。",
    componentTypes: ["decision_policy_definition"]
  }
];

export function getStrategyComponentLayer(slug: string): StrategyComponentLayer | undefined {
  return strategyComponentLayers.find((layer) => layer.slug === slug);
}
