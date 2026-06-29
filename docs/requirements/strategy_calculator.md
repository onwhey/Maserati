# StrategyCalculator 需求说明

## 1. 模块定位

StrategyCalculator 是策略分析与目标仓位映射链路的纯计算框架。

它把容易变化、需要市场验证的算法逻辑，与稳定的业务流程、持久化、状态管理和审计逻辑分离。

StrategyCalculator 覆盖以下计算阶段：

```text
FeatureLayer calculator
AtomicSignal calculator
DomainSignal calculator
MarketRegime calculator
StrategySignal calculator
DecisionPolicy calculator
```

业务模块负责：

```text
读取业务对象；
校验状态和放行条件；
冻结 Definition 与参数；
构造不可变 CalculatorInput；
按 algorithm_name + algorithm_version 定位 calculator；
调用 calculator；
校验 CalculatorOutput；
事务写入正式业务对象；
处理幂等、并发、unknown 和恢复；
写 AlertEvent；
向编排层返回业务结果。
```

StrategyCalculator 只负责：

```text
根据明确输入和冻结参数执行纯计算；
输出结构化计算结果；
输出计算证据和中间统计；
输出可判定的计算失败。
```

算法平权、完整组合批准、正式启用、后台自由组合回测和整包回滚统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

## 2. 设计目标

StrategyCalculator 必须实现：

```text
算法代码与业务代码分离；
算法版本可以并存；
算法替换不修改业务 service；
算法参数变化不修改 calculator 代码；
后台研究回测与正式运行复用同一算法实现；
每次业务结果可追溯到准确算法和参数；
每个算法版本具有独立中文说明；
版本包之外的算法不能自行进入正式策略；
算法错误不能绕过业务状态和交易安全边界。
```

## 3. 两类代码边界

### 3.1 策略计算代码

策略计算代码包括：

```text
特征公式；
原子条件判断；
原子强度计算；
领域聚合；
领域强度、覆盖率和一致性计算；
市场环境分类；
市场环境匹配度和分类置信度计算；
策略级输入权重；
策略方向、强度和置信度计算；
目标仓位意图映射；
target_intent / target_position_ratio 计算；
计算证据生成。
```

这些逻辑允许通过不同 algorithm_version 演进。

### 3.2 业务代码

业务代码包括：

```text
Django model；
数据库 selector / repository；
业务 service；
Definition 生命周期；
StrategyAnalysisRelease 批准、启用和组件选择；
正式运行与后台研究回测边界；
状态机；
业务外键；
MySQL 事务；
Redis 锁；
Celery task；
management command；
幂等；
异常恢复；
AlertEvent；
编排 adapter；
权限与审计。
```

普通算法变化不得要求修改这些业务职责。

## 4. 推荐代码结构

纯计算代码使用独立 Python package：

```text
apps/strategy_calculator/
  __init__.py
  contracts/
    __init__.py
    base.py
    feature_layer.py
    atomic_signal.py
    domain_signal.py
    market_regime.py
    strategy_signal.py
    decision_policy.py
  errors.py
  metadata.py
  registry.py
  feature_layer/
  atomic_signal/
  domain_signal/
  market_regime/
  strategy_signal/
  decision_policy/
```

约束：

```text
该 package 不定义 Django model；
不注册 Celery task；
不包含 management command；
不保存运行时业务状态；
不承担跨模块编排。
```

业务模块继续独立存在：

```text
apps/feature_layer/
apps/atomic_signals/
apps/domain_signals/
apps/market_regime/
apps/strategy_routing/
apps/strategy_signals/
apps/decision_snapshot/
```

## 5. 标准调用链

正式业务 service 调用 calculator 的固定流程：

```text
读取上游业务对象
→ 校验业务状态和真实外键
→ 读取并校验本轮编排开始时冻结的 StrategyAnalysisRelease ID、hash 和模块切片
→ 按切片精确读取并冻结 Definition
→ 构造包含冻结参数的 CalculatorInput DTO
→ CalculatorRegistry.resolve(algorithm_name, algorithm_version)
→ calculator.calculate(input_dto)
→ 得到 CalculatorOutput DTO
→ 业务 service 校验输出合同
→ 事务写入业务结果
→ 返回业务状态
```

Calculator 不得反向调用业务 service。

后台研究与回测 service 可以调用同一 CalculatorRegistry 和 calculator，但必须遵守 [StrategyAnalysisRelease](strategy_analysis_release.md) 规定的独立运行、独立结果和禁止正式写入边界。后台 service 不得通过给正式 service 传入绕过参数来执行回测。

## 6. Calculator 之间的关系

Calculator 之间不得直接调用。

禁止：

```text
DomainSignalCalculator 直接调用 MarketRegimeCalculator；
MarketRegimeCalculator 直接调用 StrategySignalCalculator；
一个 calculator 查询其他阶段的业务对象；
一个总 calculator 在内存中绕过中间业务对象完成整条策略链。
```

阶段关系必须通过正式业务对象表达：

```text
FeatureValue
→ AtomicSignalValue
→ DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

业务层负责逐步调用和持久化，计算层只处理当前阶段。

## 7. Calculator 基础接口

所有 calculator 必须实现统一概念接口：

```python
class CalculatorProtocol(Protocol):
    algorithm_name: str
    algorithm_version: str

    def calculate(
        self,
        calculation_input: CalculatorInput,
    ) -> CalculatorOutput:
        ...
```

实际实现可以使用 dataclass、Protocol 或等价纯 Python 类型，但必须保持：

```text
输入不可变；
参数不可变；
输出结构化；
无外部副作用；
同输入得到同输出。
```

## 8. CalculatorInput 合同

CalculatorInput 必须是不可变 DTO，并且是 calculator 唯一的计算输入。

允许包含：

```text
上游业务对象 ID 的不透明引用；
已由业务 service 校验过的数值；
方向、状态、强度等上游结果；
UTC 业务时间；
市场身份；
算法所需的小型证据摘要；
冻结的 schema identity；
frozen_params（规范化并冻结的 Definition params）；
params_hash。
```

不得包含：

```text
Django QuerySet；
Django model 实例；
数据库连接；
Redis client；
Celery task；
HTTP client；
BinanceGateway；
业务 service；
可变全局对象；
密钥或 Token。
```

CalculatorInput 中的 ID 只用于结果证据引用，calculator 不得使用 ID 查询任何存储。

## 9. CalculatorInput.frozen_params 合同

业务 service 必须在调用 calculator 前完成：

```text
读取 Definition.params；
规范化参数；
校验参数 schema；
冻结参数；
计算或确认 params_hash。
```

业务 service 必须把冻结参数和 `params_hash` 放入 CalculatorInput。calculator 只能读取 `CalculatorInput.frozen_params`，不得再接收第二份参数对象。

calculator 不得：

```text
读取数据库补充参数；
读取 env 改写公式；
读取当前时间选择参数；
根据运行模式静默改变参数；
为缺失关键参数猜测默认值；
修改 CalculatorInput.frozen_params。
```

允许 calculator 使用代码中属于算法身份的固定常量；这些常量变化必须形成不同 algorithm_version。

## 10. CalculatorOutput 合同

CalculatorOutput 必须是不可变 DTO，至少包括：

```text
calculation_status
output_schema_version
values
evidence_items
calculation_summary
error_code
error_message
```

允许的 calculation_status：

```text
succeeded
failed
```

CalculatorOutput 不使用业务状态：

```text
created
blocked
unknown
waiting
canceled
```

原因：

```text
created 表示业务对象已经持久化；
blocked 表示业务前置条件不满足；
unknown 表示业务持久化或外部状态不确定；
这些都不是纯计算结果。
```

业务 service 负责把 calculator 结果映射为业务状态。

## 11. 失败与异常合同

### 11.1 可预期计算失败

例如：

```text
输入数量不足；
分母为零；
参数越界；
状态代码无法分类；
强度无法归一化；
输入值不满足 calculator contract。
```

应返回：

```text
calculation_status = failed；
error_code 非空；
error_message 非空；
不得返回伪造正常值。
```

### 11.2 未预期程序异常

例如：

```text
代码缺陷；
未处理类型；
内部断言失败。
```

calculator 应抛出明确的 typed exception，由业务 service 捕获、记录并映射为 failed。

Calculator 不得捕获所有异常后返回 succeeded。

### 11.3 calculator 不产生 unknown

纯计算是内存内确定性过程。

`unknown` 只可能由业务层的持久化不确定、任务恢复或外部状态不确定产生。

## 12. 纯函数与确定性

相同的：

```text
algorithm_name；
algorithm_version；
CalculatorInput；
精度配置；
```

必须得到相同 CalculatorOutput。

Calculator 禁止使用：

```text
datetime.now()；
服务器本地时间；
随机数；
未传入的全局状态；
网络结果；
文件系统可变内容；
数据库当前值；
Redis 当前值；
进程启动顺序；
线程调度结果。
```

如算法确实需要随机过程，必须显式传入并记录 seed；没有经过独立需求确认时不得在正式策略链使用随机算法。

## 13. 时间规则

所有业务时间使用 UTC。

Calculator：

```text
只能使用 input DTO 中明确提供的 UTC 时间；
不得读取运行机器时区；
不得把展示时区用于计算；
不得根据调用时间改变固定快照的结果。
```

时间窗口必须在业务 service 构造输入时已经固定。

## 14. 数值与精度

正式策略计算优先使用 Decimal 或明确的可控精度。

规则：

```text
价格、收益率、强度、阈值和权重不得依赖不可控 float 持久化；
输出范围必须显式校验；
舍入模式必须属于算法合同；
除零必须返回明确失败；
NaN 和 Infinity 不得进入 CalculatorOutput.succeeded；
Decimal 写入 evidence_items 时转换为字符串。
```

允许内部使用数值库时，必须在算法需求文档中记录 dtype、精度和转换规则，并保证回测与正式运行一致；implementation 实现记录补充实际依赖、代码位置和测试入口。

## 15. CalculatorRegistry

CalculatorRegistry 使用以下唯一键：

```text
algorithm_name + algorithm_version
```

Registry 必须提供：

```text
register；
resolve；
list_registered；
validate_unique；
validate_required_algorithms；
读取只读算法 metadata。
```

规则：

```text
同一键只能注册一个实现；
缺少准确版本时必须失败；
不得按版本排序自动回退；
不得回退到名称相近版本；
不得根据 env 替换实现；
Registry 初始化后在进程内只读。
```

业务 service 必须通过 Registry 找 calculator，不得硬编码大型 if / elif 分发。

## 16. 算法 metadata

每个 calculator 必须声明只读 metadata：

```text
algorithm_name
algorithm_version
calculator_type
input_schema_version
output_schema_version
deterministic
supports_dry_run
algorithm_requirement_document_path
implementation_document_path
```

calculator_type 允许：

```text
feature_layer
atomic_signal
domain_signal
market_regime
strategy_signal
decision_policy
```

metadata 不控制正式启用状态。

所有已注册并通过文档、代码与测试一致性验证的 calculator 版本在算法库中平权。后台研究回测可以明确选择任意已验证版本；正式运行资格只由本轮冻结的已批准并已启用 StrategyAnalysisRelease 是否选中该版本决定。

“已验证算法目录”表示 CI、构建或部署验证已经确认代码、metadata、算法需求文档、implementation 实现记录和测试身份一致的 calculator 清单及验证证据。它不是新的运行等级，不保存“正式、候选、实习、观察”等状态，也不替代 StrategyAnalysisRelease 的选择和批准。

## 17. algorithm_name 规则

algorithm_name 必须：

```text
稳定；
可读；
使用 snake_case；
表达算法族而不是业务对象 ID；
不包含运行环境；
不包含策略启用状态。
```

允许示例：

```text
simple_moving_average
feature_compare
directional_consensus
rule_based_regime_classifier
domain_weighted_signal
threshold_target_position
```

禁止示例：

```text
latest_algorithm
new_strategy
production_rule
temporary_fix
best_model
final_version
```

## 18. algorithm_version 规则

algorithm_version 是计算行为的不可变身份。

以下变化必须使用不同 algorithm_version：

```text
计算公式变化；
输入解释变化；
归一化方式变化；
强度或置信度语义变化；
边界值处理变化；
舍入方式变化；
状态分类规则变化；
错误处理语义变化；
输出字段语义变化；
随机过程或 seed 规则变化。
```

相同 algorithm_version 允许的变化仅包括：

```text
不改变结果的性能优化；
不改变计算语义的代码整理；
注释和类型标注完善；
等价实现修复，并经过 golden test 证明输出完全一致。
```

如果无法证明输出完全一致，必须使用不同 algorithm_version。

## 19. 参数变化与算法变化

参数变化不自动等于算法变化。

例如：

```text
同一个 simple_moving_average calculator；
window = 20 与 window = 60；
算法公式相同；
通过不同 Definition.params 表达；
不需要两个算法需求版本文件，也不需要两个 implementation 实现记录。
```

以下通常属于参数：

```text
窗口长度；
阈值；
允许输入代码；
required 输入代码；
StrategySignal input_weights；
中性区间。
```

如果参数含义或应用顺序发生变化，则属于算法行为变化。

## 20. Definition 与 calculator 的关系

各业务模块的 Definition 负责表达：

```text
选择哪个 algorithm_name；
选择哪个 algorithm_version；
传入哪些 params；
依赖哪些上游定义；
输出哪种业务合同。
```

Definition 本身不通过“正式、候选、实习或观察算法”标签获得运行资格。正式 service 只运行本轮冻结 StrategyAnalysisRelease 切片选中的 Definition；版本包之外的 Definition 只能由后台研究与回测 service 明确选择。

calculator 负责表达：

```text
如何解释 params；
如何计算；
如何处理边界；
如何形成 CalculatorOutput。
```

业务结果必须冗余保存：

```text
algorithm_name；
algorithm_version；
params_hash；
definition_hash；
output_schema_version。
```

## 21. FeatureLayerCalculator 合同

输入：

```text
固定的 Kline 值 DTO；
必要的已计算 FeatureValue DTO；
FeatureDefinition params。
```

输出：

```text
明确 value_type 的特征值；
精度元数据；
计算证据；
失败信息。
```

不得输出方向、策略强度、策略置信度或交易语义。

## 22. AtomicSignalCalculator 合同

输入：

```text
同一 FeatureSet 的 FeatureValue DTO；
AtomicSignalDefinition params。
```

输出：

```text
方向或状态；
原子强度；
可空的原子 confidence；
is_valid 所需计算结果；
结构化证据；
失败信息。
```

AtomicSignal 计算成功只表示结果有效，不自动代表具有统计预测置信度。没有明确、可复现置信度公式时必须输出 `confidence = null`；非空值必须位于 0 到 1。

不得输出策略权重、目标仓位或订单动作。

## 23. DomainSignalCalculator 合同

输入：

```text
同一 AtomicSignalSet、同一领域的 AtomicSignalValue DTO；
DomainSignalDefinition params。
```

输出：

```text
领域 direction 或 state_code；
领域 strength；
coverage_ratio；
agreement_ratio；
结构化证据；
失败信息。
```

约束：

```text
不使用 StrategySignal 业务权重；
不输出通用 confidence；
不跨领域聚合；
不识别 MarketRegime。
```

## 24. MarketRegimeCalculator 合同

输入：

```text
同一 DomainSignalSet 中、且只属于 MarketRegimeDefinition.allowed_domain_codes 的正式 DomainSignalValue DTO；
冻结的 allowed_domain_codes；
冻结的 required_domain_codes；
MarketRegimeDefinition params。
```

输出：

```text
regime_code；
regime_scores；
regime_confidence；
classification_margin；
used_domain_signal_value_refs；
结构化证据；
失败信息。
```

约束：

```text
只做跨领域环境分类；
正式 DomainSignalSet 仍生成 market_context、trend、momentum、volatility、structure、risk_state 六个领域结果，但 calculator 只接收本算法声明允许使用的领域；
required domain 缺失时由业务 service 在调用前阻断；
未列入 allowed_domain_codes 的领域不得进入 CalculatorInput；
不生成策略方向；
不选择策略；
不计算目标仓位；
regime_confidence 不得伪装成盈利概率。
```

## 25. StrategyRouting 与 StrategyCalculator 的边界

StrategyRouting 不属于 StrategyCalculator 的可注册 calculator 类型。

StrategyRouting 使用稳定、版本化的业务规则完成确定性匹配：

```text
读取 MarketRegimeSnapshot；
按优先级匹配 StrategyRouteRule；
选择已注册的 StrategyDefinition，或明确 no_strategy；
生成 StrategyRouteDecision。
```

策略注册和策略计算由 StrategyDefinition 与 StrategySignalCalculator 承担。新增或停用策略不要求新增一种路由 calculator。

## 26. StrategySignalCalculator 合同

输入：

```text
选定的 StrategyDefinition DTO；
同一 DomainSignalSet 的 DomainSignalValue DTO；
冻结的策略 params。
```

输出：

```text
direction；
strength；
confidence；
prediction_horizon；
使用的领域输入；
实际 input_weights；
aggregation_snapshot；
conflict_snapshot；
结构化证据；
失败信息。
```

只有 StrategySignalCalculator 可以使用策略级 input_weights。

约束：

```text
不重新读取 AtomicSignalValue 参与正式加权；
不重复计算 DomainSignal；
不接收 StrategyRouteDecision 或 MarketRegimeSnapshot 参与数学计算；
不生成 target_position_ratio；
不读取账户、持仓或 PriceSnapshot；
不生成订单。
```

## 27. DecisionPolicyCalculator 合同

输入：

```text
质量放行后的 StrategySignal DTO；
StrategySignalQualityResult DTO；
冻结的 DecisionPolicyDefinition params。
```

输出：

```text
target_intent；
target_position_ratio；
target_confidence；
target_reason_code；
target_reason_summary_zh；
decision_calculation_snapshot；
结构化证据；
失败信息。
```

约束：

```text
只把策略判断映射为目标仓位意图；
不读取账户、持仓、价格或订单；
不接收 PriceSnapshot；
不接收 BinanceSyncRun；
不接收 MarketRegimeSnapshot 或 DomainSignalValue 作为二次加权输入；
不重新执行 StrategySignalCalculator；
不生成 CandidateOrderIntent；
不生成 OrderPlan；
不调用 RiskCheck；
不提交订单。
```

DecisionPolicyCalculator 是唯一允许输出 `target_position_ratio` 的 calculator。

它输出的 `target_position_ratio` 只是目标总仓位比例，不是新增下单比例、订单方向、开平仓动作或真实交易指令。

## 28. 权重规则

正式业务权重只属于 StrategySignalCalculator。

必须区分：

```text
AtomicSignal.strength           = 单项条件明显程度；
DomainSignal.strength           = 领域结论明显程度；
MarketRegime.regime_confidence  = 环境分类明确程度；
StrategySignal.input_weights    = 策略对领域输入的重视程度；
StrategySignal.strength         = 最终策略判断强度；
DecisionSnapshot.target_position_ratio = 目标仓位比例。
```

禁止把这些字段互相替代。

StrategySignalCalculator 不得同时正式加权：

```text
某个 DomainSignalValue；
以及该 DomainSignalValue 已经使用过的 AtomicSignalValue。
```

## 29. confidence 规则

Calculator 必须明确 confidence 的统计语义。

规则：

```text
输入完整只代表 valid，不自动等于 confidence = 1；
coverage 不等于 confidence；
agreement 不等于盈利概率；
regime_confidence 只表示分类明确程度；
StrategySignal.confidence 是最终策略级字段；
上游 confidence 不得逐层连乘。
```

如果 StrategySignal.confidence 被解释为概率，必须通过样本外校准验证。

未完成概率校准时，算法需求文档必须明确它只是结构化策略置信评分。

## 30. 证据合同

CalculatorOutput.evidence_items 必须：

```text
只包含复算当前结果所需的小型结构化数据；
引用实际输入 DTO 的不透明业务对象 ID；
Decimal 使用字符串；
说明中间计算与最终结果；
不包含完整 Kline 历史；
不包含全部上游对象副本；
不包含密钥；
不包含交易建议文本。
```

业务 service 负责把证据写入对应业务对象。

## 31. 算法需求文档与 implementation 实现记录

每个 calculator 算法版本必须同时区分两类文档：

```text
算法需求文档 = 在 requirements 中定义算法要怎么算、输入输出、公式、参数、边界、验证和业务语义；
implementation 实现记录 = 在 implementation 中记录代码实际怎么落地、类/函数/DTO/测试入口和实现差异。
```

算法需求文档是代码实现前的依据；implementation 实现记录不得新增算法需求文档没有定义的算法行为。代码实现时发现算法需求不完整，必须先回到 requirements 补齐需求，再继续实现。

算法需求文档应放在 requirements 下的对应模块或算法子目录，具体目录由各模块需求文件确定，例如：

```text
docs/requirements/<module>/<algorithm_or_definition>.md
```

implementation 实现记录按所属模块进入对应 implementation 目录：

```text
docs/implementation/<module>/
```

每份实现记录必须放在其实际所属模块内，例如：

```text
FeatureLayer calculator 实现记录 → docs/implementation/feature_layer/
AtomicSignal calculator 实现记录 → docs/implementation/atomic_signal/
DomainSignal calculator 实现记录 → docs/implementation/domain_signal/
DecisionPolicy calculator 实现记录 → docs/implementation/decision_snapshot/
```

不得建立跨模块的 implementation 堆放目录。implementation 实现记录与所属模块的业务实现说明使用同一模块目录，并通过独立文件明确算法名称和版本。

implementation 实现记录目录：

```text
docs/implementation/
  feature_layer/
  atomic_signal/
  domain_signal/
  market_regime/
  strategy_signal/
  decision_snapshot/
```

## 32. 每个算法版本的文档粒度

算法需求文档和 implementation 实现记录都必须能定位到明确的 `algorithm_name + algorithm_version`。

implementation 实现记录文件粒度：

```text
一个 algorithm_name + algorithm_version 对应一个独立 Markdown 文件；
文件名使用 <algorithm_name>__<algorithm_version>.md；
不同 algorithm_version 不得共用同一个文件；
同一 algorithm_version 不得存在互相冲突的多份实现记录。
```

示例：

```text
feature_layer/simple_moving_average__1.0.0.md
atomic_signal/feature_compare__1.0.0.md
domain_signal/directional_consensus__1.0.0.md
market_regime/rule_based_regime_classifier__1.0.0.md
strategy_signal/domain_weighted_signal__1.0.0.md
decision_snapshot/threshold_target_position__1.0.0.md
```

## 33. 算法需求文档内容

每个算法需求文档至少记录：

```text
algorithm_name；
algorithm_version；
calculator_type；
业务用途；
明确不负责的内容；
input schema；
output schema；
完整计算步骤；
完整计算公式；
参数含义；
标准化方法；
精度与舍入；
边界值处理；
失败条件；
错误代码；
证据结构；
防止重复计分规则；
防止前视偏差规则；
确定性要求；
计算示例；
golden test 向量；
单元测试要求；
已知限制和已知缺陷；
所需验证证据类型。
```

算法需求文档不能改变业务模块边界。

implementation 实现记录至少记录：

```text
algorithm_name；
algorithm_version；
calculator_type；
对应算法需求文档路径；
代码模块路径；
核心类 / 函数；
DTO 使用方式；
异常处理落点；
精度和序列化实现；
测试文件和测试命令；
golden test 对应关系；
与算法需求文档的差异说明。
```

implementation 实现记录不得补充新的公式、输入来源、放行条件或业务语义；如需新增，必须先修改算法需求文档。

## 34. 文档与代码一致性

每个注册 calculator 必须：

```text
metadata.algorithm_requirement_document_path 记录稳定的算法需求文档路径；
metadata.implementation_document_path 记录稳定的 implementation 实现记录路径；
算法需求文档、implementation 实现记录中的 algorithm_name 与代码完全一致；
算法需求文档、implementation 实现记录中的 algorithm_version 与代码完全一致；
算法需求文档输入输出与 DTO contract 一致；
算法需求文档公式与 golden test 一致；
implementation 实现记录中的代码路径和测试入口真实存在。
```

文档存在性、身份一致性和内容一致性必须在 CI、部署构建、算法目录验证和 StrategyAnalysisRelease 批准阶段完成。验证结果必须形成可追溯证据。

正式运行时不得打开或读取 Markdown 文件判断 calculator 是否可用。正式 service 只校验本轮冻结的版本包身份、Registry 中的精确 calculator、metadata 身份和已经形成的验证证据。

缺少算法需求文档或 implementation 实现记录的 calculator 不得进入已验证算法目录，不允许参与后台新回测组合，也不得被 StrategyAnalysisRelease 选中。

## 35. 验证与发布边界

算法版本不保存“正式、候选、实习或观察”运行身份。

验证和发布规则：

```text
已注册并通过文档、代码和测试一致性验证的算法版本可被后台研究回测选择；
后台每次回测记录完整组合指纹和验证证据；
回测成功不自动赋予正式运行资格；
正式运行资格由完整 StrategyAnalysisRelease 的验证、人工批准和启用事实统一赋予；
已批准版本包外的算法版本不得进入正式策略链路；
发现已知错误或安全问题的算法版本时，必须把它移出当前已验证算法目录和后续可选集合，但历史算法身份、历史版本包和历史结果继续保留；不为 calculator 另设“正式、候选、实习、观察”等运行等级。
```

版本包获得正式运行资格也不能自行开启真实交易。真实交易仍必须经过：

```text
StrategyAnalysisRelease 已批准且已启用；
进入 OrderPlan 前 `.env` 与 MySQL 真实交易权限同时允许；
OrderPlan；
RiskCheck；
ExecutionPreparation；
Execution。
```

## 36. 验证要求

策略相关 calculator 至少支持：

```text
时间顺序回测；
样本外验证；
walk-forward 验证；
参数敏感性测试；
消融测试；
简单基准对比；
前视偏差检查；
重复计分检查；
手续费、滑点和资金费率影响检查；
回测与正式运行结果一致性检查。
```

框架可运行不代表算法有效。

版本包之外的算法不得通过代码默认值或 Definition 开关进入正式链路。

## 37. dry-run

calculator 本身天然是纯计算，不区分是否落库。

dry-run 由业务 service 控制：

```text
构造与正式运行相同的 CalculatorInput；
调用相同 calculator；
使用包含相同冻结参数和 params_hash 的 CalculatorInput；
不持久化正式业务对象；
不写正式业务 AlertEvent；
返回 persisted = false。
```

不得维护一套单独的 dry-run 算法实现。

## 38. 回测与正式运行一致性

后台研究回测和正式运行必须调用相同：

```text
calculator class；
algorithm_name；
algorithm_version；
input DTO schema；
params 规范化；
精度和舍入规则。
```

允许差异只来自明确的数据源、输入组合和结果存储边界，不得来自另一套计算公式。

## 39. 性能要求

calculator 应支持单次业务输入的内存内计算。

规则：

```text
不执行 N+1 查询；
不执行网络请求；
不做无界历史扫描；
不把完整历史复制多次；
不在模块全局缓存跨业务请求结果；
性能优化不得改变计算结果。
```

## 40. 安全边界

StrategyCalculator 永远不得：

```text
读取 Binance API Key；
请求 Binance；
读取账户余额或持仓；
读取 PriceSnapshot；
生成 CandidateOrderIntent；
生成 ApprovedOrderIntent；
调用 RiskCheck；
调用 ExecutionPreparation；
调用 Execution；
提交或撤销订单；
修改杠杆；
发送 Hermes；
调用 DeepSeek；
写 AlertEvent；
启用真实交易。
```

## 41. 与编排层的关系

编排层不得直接调用 StrategyCalculator。

正确关系：

```text
PipelineOrchestrator
→ OrchestrationBusinessConnector
→ 业务模块 adapter
→ 业务 service
→ StrategyCalculator
```

Calculator 不接收、不保存、不解析编排 ID。

## 42. 测试要求

公共框架至少覆盖：

```text
1. Registry 可以注册不同 calculator_type。
2. algorithm_name + algorithm_version 唯一。
3. 重复注册被拒绝。
4. 缺失准确版本时失败。
5. 不回退到其他版本。
6. metadata 完整。
7. CI、构建和版本包验证确认 algorithm_requirement_document_path 和 implementation_document_path 存在且身份一致，正式运行时不读取 Markdown。
8. CalculatorInput 不接受 Django model。
9. CalculatorInput.frozen_params 不可修改，calculator 不接收第二份参数对象。
10. CalculatorOutput 只允许 succeeded / failed。
11. expected failure 返回明确 error_code。
12. 未预期异常不会被伪装为 succeeded。
13. calculator 不返回业务 unknown。
14. 相同输入和参数得到相同输出。
15. calculator 不读取当前时间。
16. calculator 不读取本地时区。
17. calculator 不访问 MySQL。
18. calculator 不访问 Redis。
19. calculator 不调用 Celery。
20. calculator 不执行网络请求。
21. calculator 不调用 BinanceGateway。
22. calculator 不调用大模型。
23. calculator 不写 AlertEvent。
24. calculator 不读取账户或持仓。
25. calculator 不生成订单对象。
26. calculator 之间不直接调用。
27. 每个算法版本有独立算法需求文档和 implementation 实现记录。
28. 算法需求文档、implementation 实现记录身份与代码 metadata 一致。
29. golden test 与算法需求文档公式一致。
30. Decimal、NaN、Infinity 和除零边界受控。
31. 回测和正式模式使用同一 calculator。
32. dry-run 不使用另一套算法。
33. StrategySignalCalculator 是唯一使用策略级权重的 calculator。
34. StrategySignal 不重复加权 DomainSignal 的底层 AtomicSignal。
35. MarketRegime confidence 不被解释为盈利概率。
36. DecisionPolicyCalculator 是唯一输出 target_position_ratio 的 calculator。
37. DecisionPolicyCalculator 不读取账户、持仓、PriceSnapshot 或 BinanceSyncRun。
38. DecisionPolicyCalculator 不把 target_position_ratio 输出为订单动作。
39. calculator 不保存或解析编排 ID。
40. 算法 metadata 不保存正式、候选、实习或观察运行身份。
41. 正式 service 只能解析 StrategyAnalysisRelease 切片指定的 calculator。
42. 后台研究回测可以选择版本包之外的可用 calculator。
43. 后台研究回测不通过正式 service 的绕过参数执行。
44. 正式与后台研究回测使用同一 calculator、DTO、参数规范化和精度规则。
```

各具体算法的数学正确性和业务效果测试由对应算法需求文档定义；implementation 实现记录补充代码级测试入口和实际执行结果。

## 43. 验收方式

至少执行：

```bash
pytest tests/strategy_calculator/
```

并检查：

```text
目标 StrategyAnalysisRelease 选中的所有 calculator 已注册；
每个 calculator 都有准确算法需求文档和 implementation 实现记录；
Registry 不存在重复键；
禁止依赖扫描通过；
golden test 通过；
相同输入的确定性测试通过；
业务 service 与 calculator contract 集成测试通过。
```

## 44. 模块影响声明

```text
读写 MySQL：否；
访问 Redis：否；
调用 Celery：否；
访问文件系统运行时数据：否；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
写 AlertEvent：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：提供纯 calculator；
涉及 AtomicSignal：提供纯 calculator；
涉及 DomainSignal：提供纯 calculator；
涉及 MarketRegime：提供纯 calculator；
涉及 StrategyRouting：不提供 calculator；StrategyRouteDecision 由业务 Service 校验和绑定，不传入 StrategySignalCalculator；
涉及 StrategySignal：提供纯 calculator；
涉及 DecisionSnapshot：提供 DecisionPolicyCalculator，只输出目标仓位意图，不读取账户或持仓；
涉及账户、PriceSnapshot、OrderPlan、RiskCheck 或 Execution：否。
```

## 45. 明确禁止

StrategyCalculator 禁止：

```text
包含业务 service；
包含 Django model；
查询数据库；
访问 Redis；
注册 Celery task；
解析 management command 参数；
读取 env 改变算法；
请求外部服务；
调用其他业务模块；
calculator 之间直接调用；
绕过中间业务对象执行整条策略链；
返回 created / blocked / unknown；
自行选择近似算法版本；
覆盖已经使用的算法行为；
在同一算法版本下改变公式；
把计算成功解释为预测正确；
把结构评分解释为盈利概率；
在多个层级重复使用同一证据；
在 StrategySignal 之外分配策略权重；
在 DecisionPolicyCalculator 之外生成目标仓位；
生成订单；
参与真实交易控制；
保存或解析编排 ID。
```

## 46. 最终验收标准

StrategyCalculator 验收通过必须满足：

```text
策略算法与业务流程明确分离；
所有 calculator 使用稳定 DTO 合同；
所有 calculator 是确定性纯计算；
受控的正式业务 service 或后台研究回测 service 是 calculator 的唯一调用入口；
calculator 之间不直接调用；
算法按 algorithm_name + algorithm_version 精确注册；
算法版本行为不可变；
参数变化和算法变化明确区分；
每个算法版本有独立算法需求文档和 implementation 实现记录；
算法需求文档归档到 requirements 下的对应模块或算法子目录；
implementation 实现记录归档到所属模块的 implementation 目录；
缺少算法需求文档或 implementation 实现记录的版本不得参与新回测或被版本包选中；
正式运行只使用本轮编排开始时冻结的已批准并已启用版本包所选算法；
后台回测和正式运行复用同一计算实现；
只有 StrategySignalCalculator 使用策略级权重；
只有 DecisionPolicyCalculator 输出目标仓位比例；
上游强度和置信度不被重复加权；
CalculatorOutput 不混入业务状态；
calculator 不访问存储、网络、账户或交易能力；
算法变化不要求修改稳定业务 service；
不涉及真实交易；
不违反项目交易红线。
```

StrategyCalculator 的最终定位是：

```text
为策略分析各阶段提供可替换、可版本化、可验证、无副作用的纯计算实现，使算法持续演进而不破坏稳定业务框架。
```
