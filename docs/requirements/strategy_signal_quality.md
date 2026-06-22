# StrategySignalQuality 需求说明

## 1. 模块定位

StrategySignalQuality 位于 StrategySignal 之后、DecisionSnapshot 之前。

它负责验证一份正式的 StrategySignal 是否完整、合法、可追溯、证据充分、未过期，并决定它是否允许进入 DecisionSnapshot。

正式链路为：

```text
DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
→ OrderPlan
```

StrategySignalQuality 回答的问题是：

```text
这份 StrategySignal 是否满足质量闸门，是否可以被 DecisionSnapshot 用来生成目标仓位意图？
```

StrategySignalQuality 不回答：

```text
当前市场应该做多还是做空；
应该选择哪个策略；
策略强度和置信评分应该怎么算；
目标仓位比例是多少；
是否应该生成订单；
订单是否通过风控；
是否应该真实下单。
```

StrategySignalQuality 是质量闸门层，不是策略生成层、目标仓位决策层、风控层、执行层、回测层或复盘分析层。

## 2. 核心职责

StrategySignalQuality 负责：

```text
接收明确的 strategy_signal_id；
校验 StrategySignal 是否是正式、可消费的 created 结果；
校验 StrategySignal 的结构完整性；
校验 direction、strength、confidence、prediction_horizon 等核心字段是否合法；
校验证据字段是否完整；
校验 StrategyDefinition、StrategyRouteDecision、DomainSignalSet、DomainSignalValue 的业务外键是否可追溯；
校验输入快照、聚合快照、冲突快照、权重快照是否自洽；
校验数据时间是否满足运行模式要求；
生成 StrategySignalQualityResult；
生成 StrategySignalQualityIssue；
在质量阻断、失败或未知时写入 AlertEvent；
支持 dry-run；
向 DecisionSnapshot 提供唯一质量放行结果。
```

StrategySignalQuality 不负责：

```text
重新计算 FeatureLayer；
重新计算 AtomicSignal；
重新计算 DomainSignal；
重新计算 MarketRegime；
重新执行 StrategyRouting；
重新执行 StrategySignal calculator；
重新选择 StrategyDefinition；
修改 StrategySignal 的方向、强度、置信评分或权重；
把 StrategySignal 转换为目标仓位；
生成 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE；
生成 OrderPlan；
生成 CandidateOrderIntent；
执行 RiskCheck；
执行 ExecutionPreparation；
提交订单；
读取 Binance；
读取账户、余额、持仓、订单或成交；
调用 DeepSeek；
判断策略是否赚钱；
做收益归因或回测统计；
提供 UI 展示。
```

## 3. 正式消费合同

StrategySignalQuality 的正式入口必须接收明确的 `strategy_signal_id`、本轮 `strategy_analysis_release_id` 和 `strategy_analysis_release_hash`。

不得自行查找最近一份 StrategySignal，不得通过编排 ID、任务 ID、时间窗口或策略代码模糊选择 StrategySignal。

正式入口只允许消费：

```text
StrategySignal.status = created；
StrategySignal.is_usable = true；
StrategySignal.allows_strategy_signal_quality = true；
StrategySignal.strategy_route_decision_id 非空；
StrategySignal.strategy_definition_id 非空；
StrategySignal.domain_signal_set_id 非空；
StrategySignal.used_domain_signal_value_ids 非空；
StrategyDefinition.status = active；
StrategyDefinition.enabled = true；
StrategySignal、StrategyRouteDecision 和 StrategyDefinition 属于同一 StrategyAnalysisRelease；
版本包唯一选择的 StrategySignalQualityRuleSet 可用且 rule_set_hash 一致。
```

以下 StrategySignal 不得进入正式质量放行：

```text
后台研究结果对象或其他版本包的 StrategySignal；
dry-run 生成的内存结果；
failed StrategySignal；
unknown StrategySignal；
allows_strategy_signal_quality = false 的 StrategySignal；
缺少真实业务外键的 StrategySignal。
```

StrategySignalService 返回 blocked 时不创建 StrategySignal，编排 adapter 不应继续调用 StrategySignalQuality。若调用方传入空 ID、不存在 ID、不可消费对象、隔离研究对象或其他版本包对象，StrategySignalQuality 必须 fail-closed，返回或写入不可下游消费的结果。

## 4. 上游读取边界

StrategySignalQuality 可以读取：

```text
StrategySignal；
StrategyDefinition；
StrategyRouteDecision；
StrategyRoutePolicy；
StrategyRouteRule；
DomainSignalSet；
DomainSignalValue；
MarketRegimeSnapshot；
必要的 AlertEvent 历史；
必要的 StrategySignalQualityResult 历史。
```

这些读取只用于质量校验和业务追溯。

StrategySignalQuality 不得把 DomainSignalValue、MarketRegimeSnapshot 或 StrategyRouteDecision 当作重新计算策略的输入，也不得再次应用策略权重。

StrategySignalQuality 不得读取：

```text
AtomicSignalValue；
AtomicSignalDefinition；
FeatureValue；
Kline；
MarketSnapshot 明细窗口；
Binance REST；
Binance WebSocket；
账户；
持仓；
订单；
成交；
PriceSnapshot。
```

如果需要证明底层证据链存在，应依赖 StrategySignal、DomainSignalSet、MarketRegimeSnapshot 等对象已经保存的 lineage、hash 和快照摘要，不得沿链路重新聚合底层信号。

## 5. 输出对象

### 5.1 StrategySignalQualityRuleSet

StrategySignalQualityRuleSet 是质量检查业务规则的不可变定义，建议字段：

```text
id
rule_set_code
rule_set_version
quality_schema_version
max_staleness_seconds
warning_blocks_decision
fail_alert_enabled
warning_alert_enabled
consecutive_failure_threshold
params
rule_set_hash
status
enabled
created_at_utc
updated_at_utc
```

规则：

```text
规则集合的业务含义或阈值变化必须创建新版本和新 rule_set_hash；
历史 RuleSet 不得覆盖；
status = active 且 enabled = true 只表示可供版本包选择；
一个 StrategyAnalysisRelease 必须且只能选择一个 RuleSet；
正式服务不得按最新版本、环境变量或全局 active 状态自动选择 RuleSet；
后台研究可选择其他 RuleSet，但结果与正式质量结果隔离。
```

正式版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

### 5.2 StrategySignalQualityResult

StrategySignalQualityResult 是 StrategySignal 质量检查的不可变结果。

建议字段：

```text
id
quality_result_key
strategy_signal_id
strategy_signal_key
strategy_analysis_release_id
strategy_analysis_release_hash
strategy_signal_quality_rule_set_id
strategy_route_decision_id
strategy_definition_id
domain_signal_set_id
market_regime_snapshot_id
strategy_code
strategy_version
algorithm_name
algorithm_version
quality_schema_version
quality_rule_set_version
quality_rule_set_hash
validation_mode
reference_time_utc
validation_as_of_utc
market_as_of_utc
status
quality_status
quality_score
is_usable
allows_decision_snapshot
issue_count
warning_count
error_count
critical_count
blocked_reason
error_code
error_message
check_summary
summary_text_zh
created_at_utc
updated_at_utc
business_request_key
trace_id
trigger_source
```

`status` 表示质量检查流程状态：

```text
created
blocked
failed
unknown
```

语义：

```text
created：质量检查完成并形成确定结果；
blocked：输入或前置条件不满足，无法形成可用质量结果；
failed：检查过程发生明确失败；
unknown：持久化或结果状态无法确认。
```

`quality_status` 只在 `status = created` 时有业务意义：

```text
passed
warning
failed
```

语义：

```text
passed：质量检查通过；
warning：存在非阻断质量问题；
failed：存在阻断性质量问题。
```

下游放行规则：

```text
status = created 且 quality_status = passed 且 is_usable = true 且 allows_decision_snapshot = true
→ DecisionSnapshot 可以消费；

status = created 且 quality_status = warning
→ 是否允许 DecisionSnapshot 消费由质量规则配置决定，默认允许，但必须记录 warning；

status = created 且 quality_status = failed
→ is_usable = false，allows_decision_snapshot = false；

status = blocked / failed / unknown
→ is_usable = false，allows_decision_snapshot = false。
```

### 5.3 StrategySignalQualityIssue

StrategySignalQualityIssue 记录单个质量问题。

建议字段：

```text
id
quality_result_id
issue_code
severity
check_group
check_name
field_name
message_zh
details
created_at_utc
```

`severity` 允许：

```text
info
warning
error
critical
```

默认映射：

```text
info      → 不改变 quality_status；
warning   → quality_status 至少为 warning；
error     → quality_status = failed；
critical  → quality_status = failed。
```

质量规则可以把某些 warning 配置为阻断，但必须进入 `quality_rule_set_hash`，并写入 `check_summary`。

## 6. 结构完整性检查

必须检查：

```text
StrategySignal 是否存在；
StrategySignal.status 是否为 created；
StrategySignal.is_usable 是否为 true；
StrategySignal.allows_strategy_signal_quality 是否为 true；
StrategySignal.strategy_analysis_release_id / hash 是否与本轮一致；
direction 是否存在且属于 bullish / bearish / neutral；
strength 是否存在；
confidence 是否存在；
confidence_semantics 是否存在；
prediction_horizon 是否存在；
evidence_text_zh 是否存在；
evidence_items 是否存在；
strategy_route_decision_id 是否存在；
strategy_definition_id 是否存在；
domain_signal_set_id 是否存在；
market_regime_snapshot_id 是否存在；
used_domain_signal_value_ids 是否存在且为去重列表；
actual_input_weights 字段结构是否合法；
aggregation_snapshot 是否存在；
conflict_snapshot 是否存在；
definition_hash / params_hash / algorithm identity 是否可追溯。
```

结构完整性检查只检查 StrategySignal 已经冻结的对象和快照，不重新读取上游 service 生成新的输入。

## 7. 数值合法性检查

必须检查：

```text
strength 是有限 Decimal 或等价精确数值；
confidence 是有限 Decimal 或等价精确数值；
0 <= strength <= 1；
0 <= confidence <= 1；
strength 不是 NaN；
confidence 不是 NaN；
strength 不是 Infinity；
confidence 不是 Infinity；
prediction_horizon 符合 StrategyDefinition 和算法合同；
direction 与 aggregation_snapshot 中的最终方向一致；
strength 与 aggregation_snapshot 中的最终强度一致；
confidence 与 aggregation_snapshot 中的最终置信评分一致。
```

注意：

```text
neutral 不要求 strength 必然很低；
confidence 不得被解释为盈利概率，除非算法需求文档声明并完成独立概率校准；
confidence 不得被解释为目标仓位比例；
strength 不得被解释为目标仓位比例。
```

如果发现 `direction = neutral` 但强度很高，可以记录 warning，但不得仅凭这一点判定 failed。

## 8. 业务追溯检查

必须检查：

```text
StrategySignal 绑定的 StrategyRouteDecision 真实存在；
StrategyRouteDecision.status = created；
StrategyRouteDecision.route_outcome = selected；
StrategyRouteDecision.is_usable = true；
StrategyRouteDecision.allows_strategy_signal = true；
StrategyRouteDecision.selected_strategy_definition_id 与 StrategySignal.strategy_definition_id 一致；
StrategyDefinition 真实存在；
StrategyDefinition.strategy_code / strategy_version 与 StrategySignal 一致；
StrategyDefinition.algorithm_name / algorithm_version 与 StrategySignal 一致；
StrategyDefinition.definition_hash 与 StrategySignal 冻结记录一致；
DomainSignalSet 真实存在；
DomainSignalSet.status = created；
DomainSignalSet.is_usable = true；
used_domain_signal_value_ids 全部真实存在；
全部 used DomainSignalValue 属于同一个 DomainSignalSet；
全部 used DomainSignalValue.status = created；
全部 used DomainSignalValue.is_valid = true；
全部 used domain_code 位于 StrategyDefinition.allowed_domain_codes；
StrategyDefinition.required_domain_codes 全部存在于 used_domain_signal_value_ids 对应的 domain_code 集合中；
MarketRegimeSnapshot 真实存在；
MarketRegimeSnapshot 与 StrategyRouteDecision 绑定关系一致；
MarketRegimeSnapshot 与 DomainSignalSet 的业务链路一致；
StrategySignal、StrategyRouteDecision、StrategyDefinition、MarketRegimeSnapshot 和 DomainSignalSet 的 StrategyAnalysisRelease 身份一致；
质量 RuleSet 是本轮版本包唯一选择的规则集合且 rule_set_hash 一致。
```

StrategySignalQuality 可以读取 DomainSignalValue 的 ID、domain_code、状态、hash 和必要摘要来验证追溯关系。

不得读取 DomainSignalValue 后重新计算策略方向、强度、置信评分或权重。

## 9. 快照一致性检查

必须检查：

```text
StrategyRouteDecision、StrategyRouteRule、StrategyDefinition 的路由事实一致；
DomainSignalSet、used_domain_signal_value_ids、allowed_domain_codes、required_domain_codes 的输入事实一致；
aggregation_snapshot 与 StrategySignal.direction / strength / confidence 一致；
conflict_snapshot 能解释最终方向，尤其是 neutral；
actual_input_weights 只引用 used_domain_signal_value_ids 对应的 domain_code；
actual_input_weights 与 StrategyDefinition.domain_input_weights 和 params_hash 一致；
evidence_items 中引用的 domain_code 和 used_domain_signal_value_ids 可追溯；
evidence_items 不复制完整 DomainSignalValue、AtomicSignalValue、FeatureValue 或 Kline；
证据和摘要中的 hash、schema_version、algorithm identity 与 StrategySignal 主字段一致。
```

禁止以下情况通过质量检查：

```text
actual_input_weights 包含 AtomicSignal 权重；
actual_input_weights 包含 MarketRegime 权重；
同一 DomainSignalValue 被重复加权；
evidence_items 引用不存在的输入；
StrategySignal 记录的 used_domain_signal_value_ids 与 DomainSignalSet、evidence_items 或 aggregation_snapshot 不一致；
aggregation_snapshot 与主字段不一致；
StrategyRouteDecision 指向另一个策略定义；
MarketRegimeSnapshot 被二次用于改变 strength 或 confidence。
```

## 10. 证据充分性检查

必须检查：

```text
evidence_text_zh 非空；
evidence_text_zh 面向中文审计可读；
evidence_items 非空；
evidence_items 结构符合 StrategySignal schema；
evidence_items 包含策略生成依据；
evidence_items 包含实际使用的领域输入引用；
evidence_items 包含权重、聚合、冲突处理或 neutral 原因摘要；
created + bullish / bearish / neutral 都有明确结构化证据；
warning 或 failed 的质量结果必须能追溯到具体 issue。
```

StrategySignalQuality 不使用大模型判断文字质量。

如果 `evidence_text_zh` 文案一般但结构化证据完整，可以记录 warning；只有证据缺失、不可追溯或与结构化快照冲突时才应 failed。

## 11. 数据新鲜度检查

StrategySignalQuality 必须支持以下验证模式：

```text
live
replay
backfill
manual
```

live 模式：

```text
使用 StrategySignal 或其快照中冻结的 market_as_of_utc / analysis_close_time_utc；
使用 reference_time_utc 或 validation_as_of_utc 判断是否过期；
超过质量规则配置的最大时效时记录 warning 或 failed；
生产正式链路如果配置为严格时效，过期必须 failed。
```

replay / backfill 模式：

```text
必须使用调用方传入的 reference_time_utc；
不得使用真实 now() 判断历史信号是否过期；
不得因为历史时间早于当前时间而判定 failed。
```

manual 模式：

```text
允许人工指定 reference_time_utc；
如果未指定，必须明确使用 validation_as_of_utc；
结果必须记录实际采用的时间基准。
```

如果无法从 StrategySignal、DomainSignalSet 或冻结快照中取得 `market_as_of_utc` / `analysis_close_time_utc`，应记录：

```text
missing_market_as_of_utc
```

该问题的严重程度由质量规则配置决定。

## 12. 幂等与并发

StrategySignalQuality 必须支持幂等。

`quality_result_key` 至少基于：

```text
strategy_signal_id
quality_schema_version
quality_rule_set_hash
validation_mode
reference_time_utc
```

同一 StrategySignal 在同一规则集、同一验证模式、同一 reference time 下重复执行，必须返回已有等价结果，不得重复写入质量结果。

并发要求：

```text
使用数据库唯一约束保护 quality_result_key；
使用事务原子写入 StrategySignalQualityResult、Issue 和必要 AlertEvent；
可使用 Redis 短期锁降低并发冲突；
Redis 锁失效不得破坏数据库唯一性；
事务中不得访问外部网络服务。
```

`business_request_key` 由调用方显式传入，用于业务请求幂等，不得包含 Celery task id、worker 名称、当前时间、随机重试序号或编排 ID。

## 13. unknown 与恢复

当持久化结果无法确认时，StrategySignalQuality 可以返回 `unknown`。

unknown 处理规则：

```text
不得假设质量检查失败；
不得立即重复写入新结果；
必须先按 business_request_key 查询；
必须再按 quality_result_key 查询；
核对 StrategySignal、rule_set_hash、validation_mode、reference_time_utc；
无法确认时保持 unknown，并写入 AlertEvent；
受控恢复可以重新核验，但不得覆盖已有 created 结果。
```

## 14. DecisionSnapshot 消费合同

DecisionSnapshot 只允许消费：

```text
StrategySignalQualityResult.status = created；
StrategySignalQualityResult.is_usable = true；
StrategySignalQualityResult.allows_decision_snapshot = true；
StrategySignalQualityResult.quality_status = passed 或被配置允许的 warning；
StrategySignal.status = created；
StrategySignal.is_usable = true；
StrategySignal.allows_strategy_signal_quality = true；
StrategySignalQualityResult 与 StrategySignal 属于同一 StrategyAnalysisRelease；
StrategySignalQualityResult 使用该版本包选择的 StrategySignalQualityRuleSet。
```

DecisionSnapshot 必须接收明确的 `strategy_signal_quality_result_id`，不得跳过 StrategySignalQuality 直接消费 StrategySignal。

StrategySignalQuality 不得生成：

```text
target_intent；
target_position_ratio；
target_confidence；
NO_TRADE；
NO_TARGET_CHANGE；
TARGET_POSITION。
```

StrategySignalQuality 只负责说明 StrategySignal 是否能进入 DecisionSnapshot。如何把策略判断转换为目标仓位，由 DecisionSnapshot 和 DecisionPolicy 负责。

## 15. 与编排层的关系

StrategySignalQuality 是业务模块，不承担编排职责。

业务表不得保存或查询：

```text
OrchestrationRun ID；
StepRun ID；
步骤序号；
编排内部状态；
```

编排层可以通过独立关联表记录本轮编排生成的 `strategy_signal_quality_result_id`，用于整轮追溯。

`StrategySignalQualityStepAdapter` 负责：

```text
调用 StrategySignalQualityService；
理解 created、blocked、failed、unknown；
理解 passed、warning、failed；
把业务结果映射为统一步骤状态；
在 allows_decision_snapshot = true 时允许编排继续 DecisionSnapshot；
在 blocked / failed / unknown 或 allows_decision_snapshot = false 时按统一规则停止后续策略链；
返回 strategy_signal_quality_result_id 和对象引用。
```

编排关联只提供整轮快捷查询，不替代业务外键。

## 16. AlertEvent

StrategySignalQuality 必须在以下场景写入 AlertEvent：

```text
strategy_signal_quality_blocked；
strategy_signal_quality_failed；
strategy_signal_quality_unknown；
strategy_signal_quality_issue_critical；
strategy_signal_quality_issue_error；
strategy_signal_missing；
strategy_signal_not_consumable；
strategy_signal_non_formal_rejected；
strategy_signal_lineage_invalid；
strategy_signal_snapshot_inconsistent；
strategy_signal_evidence_missing；
strategy_signal_value_out_of_range；
strategy_signal_stale；
strategy_signal_quality_consecutive_failed。
```

默认不写 AlertEvent 的场景：

```text
quality_status = passed；
普通 warning 且未超过告警阈值；
dry-run。
```

连续失败告警可以按以下维度统计：

```text
strategy_code
strategy_version
algorithm_name
algorithm_version
issue_code
```

AlertEvent 至少包含：

```text
strategy_signal_id
quality_result_id
strategy_code
strategy_version
quality_status
failed_issue_codes
trace_id
trigger_source
summary_text_zh
```

StrategySignalQuality 只写 AlertEvent，不直接发送 Hermes。

## 17. 配置规则

允许环境配置：

```text
STRATEGY_SIGNAL_QUALITY_IDEMPOTENCY_LOCK_TTL_SECONDS
STRATEGY_SIGNAL_QUALITY_MAX_CHECK_COUNT
STRATEGY_SIGNAL_QUALITY_MAX_EXECUTION_SECONDS
```

配置要求：

```text
必须有测试默认值；
必须进入 .env.example 并带中文注释；
不得通过 env 改变 StrategySignal 方向、强度、置信评分或权重；
不得通过 env 选择另一套策略算法；
不得通过 env 选择 RuleSet 或修改时效、warning 放行、严重程度和连续失败阈值；
不得通过 env 跳过质量检查进入 DecisionSnapshot。
```

质量 schema、最大时效、warning 是否阻断、告警规则和连续失败阈值必须由 StrategySignalQualityRuleSet 表达。质量规则变更必须创建新 RuleSet、改变 `quality_rule_set_hash` 并形成新的 StrategyAnalysisRelease；历史结果不得被静默改写。

## 18. dry-run 与 confirm-write

dry-run 必须：

```text
读取明确的 StrategySignal；
执行与正式模式相同的质量检查；
返回完整检查摘要；
标记 persisted = false；
不写 StrategySignalQualityResult；
不写 StrategySignalQualityIssue；
不写 AlertEvent；
不修改数据库；
不允许 DecisionSnapshot 消费内存结果。
```

如果提供 confirm-write，只能控制是否落库，不得改变：

```text
质量规则；
放行标准；
严重程度映射；
时间判断；
AlertEvent 条件。
```

## 19. 后续扩展边界

以下能力可以后续扩展，但不属于 P0 必需质量闸门：

```text
基于结构化 evidence_items 的更强自洽性检查；
同一策略最近 N 次 direction flip 频率检查；
strength 突变检查；
confidence 突变检查；
blocked、failed、neutral 比例检查；
策略风格一致性检查；
质量评分 quality_score 的复杂模型。
```

扩展规则：

```text
P0 不用时间序列稳定性、策略风格一致性或复杂 quality_score 作为硬阻断依据；
质量闸门优先由明确 issue 的 severity 决定；
这些扩展不得修改 StrategySignal 原始字段；
不得重新执行 StrategySignal calculator；
不得读取账户、订单、成交、收益回测或 AIReview 结论改变实时质量放行；
如果某项扩展会影响 DecisionSnapshot 放行，必须进入 StrategySignalQualityRuleSet、改变 quality_rule_set_hash，并形成新的 StrategyAnalysisRelease。
```

`quality_score` 可以作为审计和排序字段保留；在没有独立验证前，不得把复杂质量评分作为唯一阻断依据。

## 20. Management command

建议提供命令：

```bash
python manage.py validate_strategy_signal --strategy-signal-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

建议参数：

```text
--strategy-signal-id
--strategy-analysis-release-id
--strategy-analysis-release-hash
--business-request-key
--validation-mode live|replay|backfill|manual
--reference-time-utc
--dry-run
--confirm-write
--trace-id
--trigger-source
```

command 只允许：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 StrategySignalQualityService；
输出结构化结果。
```

command 不得实现质量检查逻辑，不得读取 Binance，不得生成 DecisionSnapshot。

## 21. 服务边界

核心业务流程必须放在 service/domain 层。

建议服务入口：

```text
validate_strategy_signal(
    strategy_signal_id,
    strategy_analysis_release_id,
    strategy_analysis_release_hash,
    expected_quality_rule_set_hash,
    business_request_key,
    validation_mode,
    reference_time_utc,
    dry_run,
    trace_id,
    trigger_source,
)
```

返回结构至少包含：

```text
status
quality_result_id
quality_result_key
strategy_signal_id
strategy_analysis_release_id
strategy_analysis_release_hash
strategy_signal_quality_rule_set_id
quality_status
is_usable
allows_decision_snapshot
issue_count
warning_count
error_count
critical_count
error_code
error_message
trace_id
```

## 22. 测试要求

至少覆盖：

```text
同一版本包的正常正式 StrategySignal → quality passed；
后台研究结果对象或其他版本包 StrategySignal → blocked 且不允许 DecisionSnapshot；
空 strategy_signal_id 或不存在的 StrategySignal → blocked；
上游 StrategySignalService blocked 且没有 strategy_signal_id → adapter 不调用 StrategySignalQuality；
failed StrategySignal → blocked；
unknown StrategySignal → blocked；
allows_strategy_signal_quality = false → blocked；
缺失 StrategyRouteDecision → failed；
RouteDecision 非 selected → failed；
StrategyDefinition 不可追溯 → failed；
DomainSignalSet 不可追溯 → failed；
used_domain_signal_value_ids 为空 → failed；
used DomainSignalValue 不属于同一 DomainSignalSet → failed；
used domain_code 不在 allowed_domain_codes → failed；
required_domain_codes 缺失 → failed；
direction 非法 → failed；
strength 越界 → failed；
confidence 越界 → failed；
NaN / Infinity → failed；
prediction_horizon 缺失 → failed；
confidence_semantics 缺失 → failed；
evidence_text_zh 缺失 → failed；
evidence_items 缺失 → failed；
used_domain_signal_value_ids 与 DomainSignalSet、evidence_items 或 aggregation_snapshot 不一致 → failed；
aggregation_snapshot 与主字段不一致 → failed；
actual_input_weights 引用 AtomicSignal → failed；
actual_input_weights 引用 MarketRegime → failed；
同一 DomainSignalValue 被重复加权 → failed；
neutral 且 strength 很高 → warning，不自动 failed；
direction flip、strength 突变、confidence 突变等扩展检查不作为 P0 硬阻断；
live 模式数据过期 → warning 或 failed；
replay 模式不使用真实 now()；
dry-run 不写库、不写 AlertEvent；
quality failed 写 AlertEvent；
quality passed 不写 AlertEvent；
幂等重复执行返回已有结果；
并发执行只产生一份等价结果；
unknown 先查 business_request_key 和 quality_result_key；
DecisionSnapshot 不能消费 dry-run 内存结果；
业务表不保存编排 ID；
版本包未选择 RuleSet 或选择多个 RuleSet → blocked；
RuleSet 非 active、disabled 或 rule_set_hash 不一致 → blocked；
环境变量不能替代 RuleSet 改变质量业务规则；
正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

## 23. 验收方式

实现完成后至少执行：

```bash
pytest tests/strategy_signal_quality/
python manage.py validate_strategy_signal --strategy-signal-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id> --dry-run
python manage.py validate_strategy_signal --strategy-signal-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

数据库至少检查：

```text
StrategySignalQualityResult 正确绑定 StrategySignal；
StrategySignalQualityResult 正确绑定 StrategyAnalysisRelease 与 RuleSet；
StrategySignalQualityIssue 正确绑定 Result；
quality_result_key 幂等；
quality_rule_set_hash 已记录；
allows_decision_snapshot 只在质量放行时为 true；
failed / blocked / unknown 结果写入必要 AlertEvent；
dry-run 没有写入正式业务对象；
业务表没有保存编排 ID。
```

通过标准：

```text
只有同一版本包内 created 且质量通过的 StrategySignal 可以进入 DecisionSnapshot；
后台研究、其他版本包、阻断、失败、未知和 dry-run 结果都不能进入 DecisionSnapshot；
质量检查不修改 StrategySignal 原始结果；
质量检查不重新执行 StrategySignal calculator；
质量检查不读取 AtomicSignal、Feature、Kline、账户、持仓、价格或订单；
MySQL 保存正式质量事实；
Redis 只作为短期锁、幂等或缓存辅助；
所有业务时间使用 UTC；
不访问 Binance；
不调用 DeepSeek；
不涉及真实交易。
```

## 24. 模块影响声明

```text
读写 MySQL：是，读取 StrategySignal、StrategyDefinition、StrategyRouteDecision、DomainSignalSet、DomainSignalValue、MarketRegimeSnapshot，写 StrategySignalQualityResult、StrategySignalQualityIssue 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：否；
涉及 AtomicSignal：否；
涉及 DomainSignal：只做业务追溯校验，不重新计算；
涉及 MarketRegime：只做业务追溯校验，不重新分类或加权；
涉及 StrategyRouting：只校验 StrategyRouteDecision，不重新路由；
涉及 StrategySignal：是，验证其质量；
涉及 DecisionSnapshot：只提供放行结果，不生成目标仓位；
涉及 Binance Account Sync：否；
涉及 PriceSnapshot：否；
涉及 OrderPlan / CandidateOrderIntent：否；
涉及 RiskCheck / ApprovedOrderIntent：否；
涉及 ExecutionPreparation / Execution：否；
涉及 OrderStatusSync / FillSync / PerformanceMetrics / AIReview：否；
写 AlertEvent：质量阻断、失败、未知或严重 issue 时写；
dry-run：执行同样检查但不写库；
confirm-write：如提供，只控制落库，不改变质量规则。
```

## 25. 明确禁止

StrategySignalQuality 禁止：

```text
绕过 StrategySignal 直接读取 DomainSignal 生成质量放行；
读取 AtomicSignalValue、FeatureValue 或 Kline；
重新执行 StrategySignal calculator；
重新选择 StrategyDefinition；
把 MarketRegime 再次用于方向、权重、strength 或 confidence；
把 confidence 解释为盈利概率；
把 strength 或 confidence 解释为目标仓位；
修改 StrategySignal 原始字段；
把质量失败改写成 neutral；
生成 DecisionSnapshot；
生成 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
请求 Binance；
调用 DeepSeek 参与实时判断；
保存或查询编排 ID；
让 dry-run 结果进入正式下游。
```

StrategySignalQuality 的最终定位是：

```text
验证 StrategySignal 质量，保护 DecisionSnapshot 不消费坏信号，并记录可审计、可追溯的质量事实。
```
