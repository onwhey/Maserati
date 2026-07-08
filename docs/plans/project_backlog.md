# 项目待办事项目录

本文档只做待办目录，不承载完整需求。

具体设计、规则、字段、算法、验收标准，仍然写回对应 requirements / architecture / plans 文件。

## 使用规则

```text
做 A 时发现 B / C / D，就先记到这里；
开始新阶段前，先扫一遍这里；
进入正式设计后，把细节迁回对应文档；
完成后只保留简短完成记录，避免本文档膨胀。
```

状态：

```text
待确认 / 待补文档 / 待实现 / 待验证 / 暂缓 / 已完成 / 已废弃
```

优先级：

```text
P0 = 阻断当前主线
P1 = 影响下一阶段判断
P2 = 有价值但可后置
P3 = 研究或观察项
```

## 当前主线

```text
MarketRegime 状态延续与切换确认
→ MarketRegime 如何消费 Structure 支撑/压力事实
→ RiskState 极端冲击识别与冲击后观察
→ Strategy 如何消费 MarketRegime / Structure
→ 策略本身是否有效
→ 目标仓位到订单提交的正式后半链路验收
```

## 待办目录

| 编号 | 状态 | 优先级 | 事项 | 归属文档 | 下一步 |
|---|---|---:|---|---|---|
| TODO-000 | 待复核 | P0 | 复核领域信号六个领域层的实现逻辑 | `docs/plans/domain_signal_review_checklist.md` | 逐一复核 market_context、trend、momentum、volatility、structure、risk_state 的 Feature/Atomic/DomainSignal 口径，确认是否存在“名字过重、算法过粗、主结论误导、可选证据越权”等问题 |
| TODO-001 | 待补文档 | P0 | 新版支撑/压力算法：用有效局部低点/高点定义结构位 | `docs/plans/structure_v2_evidence_matrix.md` / `docs/requirements/domain_signals/structure_domain_signals_v2.md` | 先写清楚：宽价格聚类区只能叫历史反应区；真正支撑/压力必须来自局部低点/高点，并满足反弹/回落幅度、时间间隔、区间宽度和当前确认条件 |
| TODO-002 | 已完成 | P0 | Structure v2 支撑/压力并存表达验证 | `docs/plans/structure_v2_evidence_matrix.md` | id59 / id60 已完成验证：Structure 输出包含 support_resistance_context，并补充说明“不是单边结构” |
| TODO-004 | 待补文档 | P1 | 策略插件清单补全，包括保守/标准/进攻/公用策略 | `docs/requirements/strategy_portfolio_templates.md` | 建立 MarketRegime × 策略插件矩阵 |
| TODO-005 | 暂缓 | P2 | 策略路由后台页面继续简化 | `docs/requirements/ops_console.md` | 等策略插件清单稳定后再改页面 |
| TODO-006 | 暂缓 | P1 | 目标仓位映射过小，后续需要 position_policy_v2 | `docs/requirements/decision_snapshot/position_policy_v1.md` | 先完成策略判断验收，再单独设计仓位映射 |
| TODO-007 | 待确认 | P3 | 江恩时间机制作为实验性可选证据块 | 待新建或补充对应 Feature / Atomic 文档 | 先定义到底计算什么、如何验证 |
| TODO-008 | 暂缓 | P1 | 正式交易后半链路验收 | `docs/plans/trading_execution_implementation_plan.md` | 策略和目标仓位稳定后再验收 |
| TODO-009 | 暂缓 | P2 | 回测详情复盘页继续增强 | `docs/requirements/strategy_backtest.md` / `docs/requirements/ops_console.md` | 等 Structure / MarketRegime / Strategy 口径稳定后再做 |
| TODO-010 | 待验证 | P1 | StrategyRouteRule 展示名数据迁移在本地库执行 | `apps/strategy_analysis/migrations/0019_strategy_route_rule_display_names.py` | 执行 `manage.py migrate strategy_analysis` 后确认策略路由页显示来源正确 |
| TODO-011 | 暂缓 | P3 | MarketRegime 定义是否需要数据库化和后台管理 | `docs/requirements/strategy_routing.md` | 只有当 MarketRegime 需要后台编辑时再单独设计，目前保持代码契约 |
| TODO-012 | 已完成 | P0 | MarketRegime v5 结构破坏确认版 | `docs/requirements/market_regime/context_structure_regime_v5.md` | 代码和第一轮回测已完成；问题收敛到 Structure 证据不足，不继续微调 v5 |
| TODO-013 | ???? | P2 | ????????????? | `docs/requirements/ops_console.md` / `docs/requirements/domain_signals/strategy_domain_design.md` | ????? AtomicSignalDefinition ??????????????????????? definition_hash ????????? deprecated / disabled ?? |

## 已完成但保留观察

| 编号 | 状态 | 事项 | 完成证据 | 后续观察 |
|---|---|---|---|---|
| DONE-001 | 已完成 | Structure 1.1：720 天历史大结构参考位改为可选证据块 | id44 未选择原子不显示；id45 选择原子后显示且远离时不进入中文证据；含历史大结构原子的 Structure 定义版本归为 1.1.0 | 继续观察该证据是否真的有交易价值 |
| DONE-002 | 已完成 | StrategyRouting 页面市场环境展示来源与 RouteRule 边界拆分 | 新增 MarketRegime 统一定义目录；接口返回 market_regime_display_name；前端不再用 Rule display_name 当市场环境名 | 若后续 MarketRegime 允许后台编辑，再单独设计 MarketRegime 定义表 |
| DONE-003 | 已完成 | 可选证据块框架第一版落地 | Structure 的 historical_major_reference 已按可选证据块处理；未选择对应原子时不进入领域摘要 | 等第二类可选证据块出现后再判断是否继续抽象 |
| DONE-004 | 已完成 | MarketRegime v3 大样本验收结论整理 | `docs/plans/market_regime_acceptance_matrix.md` 已记录 v3 在多头顶部/回调识别上的问题 | v3 不作为下一步主线，后续以 v4 验收为主 |
| DONE-005 | 已完成 | MarketRegime v4 结构证据增强版设计和代码实现 | 已新增 v4 requirements、calculator 注册与测试；不再依赖 v2/v3 层层继承 | 下一步只做回测验收，不继续扩功能 |
| DONE-006 | 已完成 | MarketRegime v4 第一轮回测验收结论整理 | `docs/plans/market_regime_acceptance_matrix.md` 已记录回测 ID 46–49 的结论：v4 可保留，但下一步进入 v5 | v5 聚焦结构保持、结构破坏、结构修复确认，不再继续微调 v4 |
| DONE-007 | 已完成 | MarketRegime v5 结构破坏确认版代码落地 | 新增 `context_structure_regime/v5` calculator 注册、默认定义和单元测试；MarketRegime 计算器测试 21 passed，定义/服务测试 18 passed | 下一步用 v5 版本包回测 2025-02-01→2025-04-15、2025-10-15→2025-11-02、2026-02-15→2026-05-15 等关键窗口 |
| DONE-008 | 已完成 | MarketRegime v5 第一轮回测验收结论整理 | `docs/plans/market_regime_acceptance_matrix.md` 已记录回测 ID 50–53：v5 大方向可保留，但确认破坏/修复分支未充分触发 | 主线回到 Structure，补足跌破候选、突破候选、确认跌破、确认突破等结构事实 |
| DONE-009 | 已完成 | Structure v2 支撑/压力守住口径修正 | id55 暴露旧口径只识别“支撑上方/压力下方”；已改为“进入区间但未跌破/突破也算守住/压住”，旧 4 条 holds 定义本地停用，新 4 条定义 active；相关测试 33 passed | 后续重新生成版本包并复测 id55 同一区间 |
| DONE-010 | 已完成 | Structure v2 支撑/压力并存表达代码落地 | `GroupedAtomicAggregationV2Calculator` 已新增 `support_resistance_context`，支撑/压力同时成立时补充说明“不是单边结构”；相关测试 25 passed | 后续重跑 id57/id58 对应日期，检查页面解释是否完整 |
| DONE-011 | 已完成 | Structure v2 支撑/压力并存表达回测验证 | 回测 id59（2026-05-10）与 id60（2026-05-16）均完成；Structure 证据记录 support_resistance_context，且显示 1d/4h 支撑与压力同时有效、当前不是单边结构 | 后续若要让 MarketRegime 消费该补充事实，需要单独设计，不在本次 Structure 表达修正内 |
| DONE-012 | 已完成 | 版本包生成自动过滤原子/特征 | 工作区生成版本包时，已按选中的 DomainSignalDefinition 倒推 AtomicSignalDefinition，再按 AtomicSignalDefinition 倒推 FeatureDefinition；额外选择但领域不消费的旧原子不会进入 release；缺少需要的原子版本会阻断生成 | 旧 release 不会自动变更，需要重新生成版本包后回测 |

## 维护规则

```text
不要在本文档写长篇需求；
只写“是什么、放哪里、下一步”；
复杂内容迁回对应文件；
完成一个事项后，新增完成证据；
如果产生新问题，新增新 TODO，不要无限扩写旧 TODO。
```
## 待办补充（正常中文）

| 编号 | 状态 | 优先级 | 事项 | 归属文档 | 下一步 |
|---|---|---:|---|---|---|
| TODO-014 | 暂缓 | P1 | 成交量没有真正进入六个领域判断，优先补动能领域的成交量确认 | `docs/plans/domain_signal_review_checklist.md` / `docs/requirements/feature_layer/momentum_features.md` / `docs/requirements/atomic_signals/momentum_atomic_signals.md` | 先让 MarketRegime 学会消费已有 Structure 事实；成交量后续作为突破、跌破、支撑承接、压力压制的确认器补充 |
| TODO-015 | 待补充 | P2 | 组件依赖高级展示与互斥/替代关系：后台需要让人看清“领域需要哪些原子、原子需要哪些特征”，并支持后续互斥/替代关系 | `docs/requirements/strategy_analysis_release.md` / `docs/requirements/ops_console.md` | 自动过滤已在生成版本包时落地；后续只补页面解释、依赖声明展示、互斥/替代关系和开发者模式 |
| TODO-016 | 已完成 | P0 | 拐点型支撑压力 AtomicSignal 与 Structure 新版聚合 | `docs/plans/structure_pivot_support_resistance_implementation_slice.md` / `docs/requirements/feature_layer/support_resistance_level_features.md` / `docs/requirements/atomic_signals/structure_pivot_support_resistance_atomic_signals.md` / `docs/requirements/domain_signals/structure_domain_signals_v3.md` | 回测 64–68 第一轮复核基本及格；Structure v3 作为“市场事实表达层”阶段通过，暂时冻结，不再对单个行情微调 |
| TODO-017 | 已完成 | P0 | MarketRegime v6：独立消费 Structure 的市场环境算法 | `docs/requirements/market_regime/context_structure_regime_v6.md` / `docs/plans/market_regime_acceptance_matrix.md` | v6 calculator、默认定义注册、单元测试和多轮回测已完成；主要问题收敛为连续区间内候选状态跳变频繁，因此下一步进入 v6.1 稳定性验证 |
| TODO-018 | 暂缓 | P1 | Strategy 如何消费 MarketRegime 与 Structure 的验收 | `docs/requirements/strategy_routing.md` / `docs/requirements/strategy_portfolio_templates.md` / `docs/requirements/strategy_signals/*.md` | 等 MarketRegime 状态延续和 Structure 消费规则稳定后，再讨论策略是否等待、追随、降低仓位、不开仓或只做确认；RiskState 极端冲击可并行或后置补充 |
| TODO-019 | 已完成 | P0 | MarketRegime v6.1：在 v6 基础上补主环境稳定规则，避免候选状态导致高频跳变 | `docs/requirements/market_regime/context_structure_regime_v6_1.md` / `docs/plans/market_regime_acceptance_matrix.md` | 回测 80–84 结论已写入验收矩阵：v6.1 能减少部分同方向子状态跳变，但不能解决顶部转熊阶段跨环境反复切换；下一步进入 TODO-021 状态延续与切换确认机制 |
| TODO-020 | 待补文档 | P1 | RiskState v2：极端盘中冲击与冲击后观察期 | `docs/plans/domain_signal_review_checklist.md` / `docs/requirements/domain_signals/risk_state_domain_signals_v2.md` | 针对 2025-10-10 这类 4h 极端下杀/上冲，补 open-low/open-high、高低波动、ATR、成交量放大、冲击后 N 根观察期；该问题重要但不排在当前第一步，先修 MarketRegime 反复切换 |
| TODO-021 | 已实现，待回测验收 | P0 | MarketRegime v7：状态延续与切换确认机制 | `docs/requirements/market_regime/context_structure_regime_v7.md` / `docs/plans/market_regime_acceptance_matrix.md` | v7 calculator 已实现并接入上一周期 MarketRegime 状态；13 个市场环境暂不变；下一步 seed MarketRegimeDefinition、发布包含 v7 的测试版本包，并用 80–84 对应窗口和 v6.1 对照回测 |
| TODO-022 | 待复核 | P1 | Trend 领域职责重新确认：长期趋势与短期趋势是否需要拆分 | `docs/plans/domain_signal_review_checklist.md` / `docs/requirements/domain_signals/trend_domain_signals.md` | 当前 Trend 更像“1d 主趋势 + 4h 注释”，在拐点阶段偏慢；复核是否需要新增更当前的短周期趋势证据，避免 MarketRegime 把长期惯性当作当前趋势 |
| TODO-023 | 待补文档 | P1 | MarketRegime 消费 Structure 支撑/压力事实的统一规则 | `docs/requirements/market_regime/context_structure_regime_v6_1.md` / `docs/requirements/domain_signals/structure_domain_signals_v3.md` | 统一定义支撑测试、支撑守住、支撑跌破候选、压力测试、压力压住、压力突破候选、支撑压力夹层如何影响 MarketRegime，避免只对单个回测窗口调规则 |
