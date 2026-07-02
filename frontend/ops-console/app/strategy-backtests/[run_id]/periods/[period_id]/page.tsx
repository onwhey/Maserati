import Link from "next/link";
import type { ReactNode } from "react";

import { ApiError } from "@/components/ops/api-error";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { displayValue } from "@/lib/utils";

type PageProps = {
  params: Promise<{ run_id: string; period_id: string }>;
};

type DomainSpec = {
  code: string;
  title: string;
  question: string;
  checkHint: string;
};

const DOMAIN_SPECS: DomainSpec[] = [
  {
    code: "market_context",
    title: "市场大背景",
    question: "大级别更像偏多、偏空还是中性？",
    checkHint: "如果这里判断错，优先检查长期特征、市场背景原子阈值和 market_context 领域聚合。"
  },
  {
    code: "trend",
    title: "趋势",
    question: "1d 主趋势和 4h 辅助趋势是否一致？",
    checkHint: "如果这里判断错，优先检查均线、斜率、趋势原子信号和 trend 聚合规则。"
  },
  {
    code: "momentum",
    title: "动能",
    question: "当前推动力是在增强、减弱还是不明确？",
    checkHint: "如果这里判断错，优先检查近期收益、推进速度、动能原子阈值和 momentum 聚合规则。"
  },
  {
    code: "volatility",
    title: "波动",
    question: "当前波动是偏低、正常、偏高还是极端？",
    checkHint: "如果这里判断错，优先检查 ATR、波动分位、极端波动原子和 volatility 聚合规则。"
  },
  {
    code: "structure",
    title: "结构位置",
    question: "价格处在支撑、压力、区间上半部还是下半部？",
    checkHint: "如果这里判断错，优先检查支撑压力区间、触碰次数、距离百分比和 structure 聚合规则。"
  },
  {
    code: "risk_state",
    title: "风险状态",
    question: "这一周期是否存在会影响信号可靠性的市场风险？",
    checkHint: "如果这里判断错，优先检查异常波动、插针、单根 K 线风险原子和 risk_state 聚合规则。"
  }
];

export default async function StrategyBacktestPeriodDetailPage({ params }: PageProps) {
  const { run_id: runId, period_id: periodId } = await params;
  const result = await opsFetch<Record<string, unknown>>(
    `/api/ops/strategy-backtests/runs/${encodeURIComponent(runId)}/periods/${encodeURIComponent(periodId)}/analysis/`
  );

  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }

  const data = result.data;
  const period = asRecord(data.period);
  const layers = asRecord(data.layers);
  const available = Boolean(data.available);

  const featureLayer = asRecord(layers.feature_layer);
  const atomicLayer = asRecord(layers.atomic_signal);
  const domainLayer = asRecord(layers.domain_signal);
  const marketRegimeLayer = asRecord(layers.market_regime);
  const routingLayer = asRecord(layers.strategy_routing);
  const signalLayer = asRecord(layers.strategy_signal);
  const qualityLayer = asRecord(layers.strategy_signal_quality);
  const decisionLayer = asRecord(layers.decision_snapshot);

  const features = asRows(featureLayer.values);
  const atomicSignals = asRows(atomicLayer.values);
  const domainSignals = asRows(domainLayer.values);
  const marketRegime = asRecord(marketRegimeLayer.object);
  const routing = asRecord(routingLayer.object);
  const signal = asRecord(signalLayer.object);
  const quality = asRecord(qualityLayer.object);
  const decision = asRecord(decisionLayer.object);
  const qualityIssues = asRows(qualityLayer.issues);

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">周期复盘解释 #{displayValue(period.period_index)}</h1>
      </div>

      <div className="mb-4 flex flex-wrap gap-3 text-sm">
        <Link className="text-muted-foreground underline hover:text-foreground" href={`/strategy-backtests/${runId}`}>
          返回回测详情
        </Link>
      </div>

      <div className="space-y-6">
        <PeriodSummaryCard period={period} />

        {!available ? (
          <Card>
            <CardContent className="pt-6 text-sm text-muted-foreground">{displayValue(data.message_zh)}</CardContent>
          </Card>
        ) : (
          <>
            <OverallConclusion
              period={period}
              domains={domainSignals}
              marketRegime={marketRegime}
              routing={routing}
              signal={signal}
              quality={quality}
              decision={decision}
            />

            <Card>
              <CardHeader>
                <CardTitle>市场事实解释</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {DOMAIN_SPECS.map((spec) => (
                  <DomainExplanation
                    key={spec.code}
                    spec={spec}
                    domain={findByCode(domainSignals, "domain_code", spec.code)}
                    atomicSignals={atomicSignals}
                    features={features}
                  />
                ))}
              </CardContent>
            </Card>

            <DecisionChainReview
              period={period}
              marketRegime={marketRegime}
              routing={routing}
              signal={signal}
              quality={quality}
              qualityIssues={qualityIssues}
              decision={decision}
            />

            <RawEvidenceDetails
              features={features}
              atomicSignals={atomicSignals}
              domainSignals={domainSignals}
              marketRegime={marketRegime}
              routing={routing}
              signal={signal}
              quality={quality}
              qualityIssues={qualityIssues}
              decision={decision}
            />
          </>
        )}
      </div>
    </>
  );
}

function PeriodSummaryCard({ period }: { period: Record<string, unknown> }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>周期摘要</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="UTC 周期" value={formatUtcMinute(period.analysis_close_time_utc)} />
        <Metric label="状态" value={<StatusBadge value={period.status} />} />
        <Metric label="周期收益" value={<ReturnPercent value={period.period_return_pct} />} />
        <Metric label="策略" value={strategyLabel(period.selected_strategy)} />
        <Metric label="目标仓位" value={formatPosition(period.target_position_ratio)} />
        <Metric label="有效仓位" value={formatPosition(period.effective_position_ratio)} />
        <Metric label="模拟成交价" value={formatDecimal(period.simulated_execution_price, 2)} />
        <Metric label="收盘价" value={formatDecimal(period.close_price, 2)} />
        <Metric label="权益" value={formatDecimal(period.equity, 2)} />
        <Metric label="原因" value={reasonLabel(period.reason_code)} />
      </CardContent>
    </Card>
  );
}

function OverallConclusion({
  period,
  domains,
  marketRegime,
  routing,
  signal,
  quality,
  decision
}: {
  period: Record<string, unknown>;
  domains: Array<Record<string, unknown>>;
  marketRegime: Record<string, unknown>;
  routing: Record<string, unknown>;
  signal: Record<string, unknown>;
  quality: Record<string, unknown>;
  decision: Record<string, unknown>;
}) {
  const marketContext = findByCode(domains, "domain_code", "market_context");
  const trend = findByCode(domains, "domain_code", "trend");
  const structure = findByCode(domains, "domain_code", "structure");
  const risk = findByCode(domains, "domain_code", "risk_state");
  const selectedStrategy = period.selected_strategy || signal.strategy_code;
  const targetPosition = decision.target_position_ratio ?? period.target_position_ratio;

  return (
    <Card>
      <CardHeader>
        <CardTitle>本周期结论</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2 rounded-xl border bg-muted/30 p-4 text-sm leading-7">
          <ConclusionLine label="大背景" value={domainConclusion(marketContext)} />
          <ConclusionLine label="趋势" value={domainConclusion(trend)} />
          <ConclusionLine label="结构" value={domainConclusion(structure)} />
          <ConclusionLine label="风险" value={domainConclusion(risk)} />
          <ConclusionLine label="市场环境" value={regimeLabel(marketRegime.regime_code)} />
          {selectedStrategy ? (
            <>
              <ConclusionLine label="策略路由" value={strategyLabel(selectedStrategy)} />
              <ConclusionLine label="目标仓位" value={formatPosition(targetPosition)} />
            </>
          ) : (
            <>
              <ConclusionLine label="策略路由" value="无具体策略" />
              <ConclusionLine label="目标仓位" value="本周期不形成新的目标仓位" />
            </>
          )}
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Metric label="市场环境" value={regimeLabel(marketRegime.regime_code)} />
          <Metric label="路由结果" value={routeOutcomeLabel(routing.route_outcome)} />
          <Metric label="策略信号" value={signal.strategy_code ? `${strategyLabel(signal.strategy_code)} / ${directionLabel(signal.direction)}` : "—"} />
          <Metric label="信号质量" value={qualityStatusLabel(quality.quality_status)} />
        </div>

        <ReviewHint>
          如果你觉得这个周期看错了，不要从最终仓位开始猜。先看“市场事实解释”里是哪一个领域判断不符合行情；再沿着该领域下的原子信号和特征值向下查。
        </ReviewHint>
      </CardContent>
    </Card>
  );
}

function DomainExplanation({
  spec,
  domain,
  atomicSignals,
  features
}: {
  spec: DomainSpec;
  domain: Record<string, unknown>;
  atomicSignals: Array<Record<string, unknown>>;
  features: Array<Record<string, unknown>>;
}) {
  const usedAtomicCodes = toStringList(domain.used_atomic_signal_codes);
  const matchedAtomicSignals = usedAtomicCodes.length
    ? usedAtomicCodes.map((code) => findByCode(atomicSignals, "signal_code", code)).filter((item) => Object.keys(item).length > 0)
    : [];

  return (
    <details className="rounded-xl border">
      <summary className="cursor-pointer p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold">{spec.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{spec.question}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <Pill>{directionLabel(domain.direction)}</Pill>
            <Pill>{stateLabel(domain.state_code)}</Pill>
            <Pill>强度 {formatDecimal(domain.strength, 2)}</Pill>
          </div>
        </div>
      </summary>

      <div className="space-y-4 border-t p-4">
        <div className="grid gap-3 lg:grid-cols-2">
          <ExplanationBlock title="这一层的结论" tone="primary">
            <NarrativeText value={domain.evidence_text_zh ? domain.evidence_text_zh : `${spec.title} 本周期没有保存中文证据摘要。`} />
          </ExplanationBlock>
          <ExplanationBlock title="如果这里看错，应该查什么" tone="warning">
            {spec.checkHint}
          </ExplanationBlock>
        </div>

        <div className="space-y-3">
          <div className="text-sm font-medium">它用了这些原子信号</div>
          {matchedAtomicSignals.length > 0 ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {matchedAtomicSignals.map((atomic) => (
                <AtomicEvidence key={String(atomic.id ?? atomic.signal_code)} atomic={atomic} features={features} />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
              这个领域没有保存可追溯的原子信号列表；可以到底部原始明细里查看全部原子信号。
            </div>
          )}
        </div>
      </div>
    </details>
  );
}

function AtomicEvidence({ atomic, features }: { atomic: Record<string, unknown>; features: Array<Record<string, unknown>> }) {
  const usedFeatureCodes = toStringList(atomic.used_feature_codes);
  const usedFeatureValueIds = toStringList(atomic.used_feature_value_ids);
  const matchedFeatures = features.filter((feature) => {
    const code = String(feature.feature_code ?? "");
    const id = String(feature.id ?? "");
    return usedFeatureCodes.includes(code) || usedFeatureValueIds.includes(id);
  });

  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">{signalLabel(atomic.signal_code)}</div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Pill>{directionLabel(atomic.direction)}</Pill>
          <Pill>强度 {formatDecimal(atomic.strength, 2)}</Pill>
          <Pill>置信 {formatDecimal(atomic.confidence, 2)}</Pill>
        </div>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        {narrativeText(atomic.evidence_text_zh || "没有保存中文证据摘要。")}
      </p>

      <div className="mt-3">
        <div className="mb-2 text-xs font-medium text-muted-foreground">它读取的特征值</div>
        {matchedFeatures.length > 0 ? (
          <div className="grid gap-2 md:grid-cols-2">
            {matchedFeatures.map((feature) => (
              <div key={String(feature.id ?? feature.feature_code)} className="rounded-md border bg-background p-2 text-xs">
                <div className="font-medium">{featureLabel(feature.feature_code)}</div>
                <div className="mt-1 text-muted-foreground">值：{featureValue(feature)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">没有匹配到具体特征值。</div>
        )}
      </div>
    </div>
  );
}

function DecisionChainReview({
  period,
  marketRegime,
  routing,
  signal,
  quality,
  qualityIssues,
  decision
}: {
  period: Record<string, unknown>;
  marketRegime: Record<string, unknown>;
  routing: Record<string, unknown>;
  signal: Record<string, unknown>;
  quality: Record<string, unknown>;
  qualityIssues: Array<Record<string, unknown>>;
  decision: Record<string, unknown>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>策略决策解释</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <DecisionStep
          title="1. 市场环境怎么得出"
          conclusion={regimeLabel(marketRegime.regime_code)}
          evidence={marketRegime.evidence_text_zh}
          hint="如果市场事实各领域都对，但市场环境分类不符合直觉，应检查 MarketRegime 的分类规则和权重。"
        />
        <DecisionStep
          title="2. 为什么选这个策略"
          conclusion={routing.route_outcome === "selected" ? strategyLabel(period.selected_strategy || signal.strategy_code) : routeOutcomeLabel(routing.route_outcome)}
          evidence={routing.evidence_text_zh || routing.selection_reason}
          hint="如果市场环境对，但策略选错，应检查 StrategyRouting 的路由规则，而不是先改特征。"
        />
        <DecisionStep
          title="3. 策略信号怎么得出"
          conclusion={
            signal.strategy_code
              ? `${strategyLabel(signal.strategy_code)}，方向 ${directionLabel(signal.direction)}，强度 ${formatDecimal(signal.strength, 2)}，置信 ${formatDecimal(signal.confidence, 2)}`
              : "本周期没有策略信号"
          }
          evidence={signal.evidence_text_zh}
          hint="如果策略选对但方向、强度或价格条件不合理，应检查具体 StrategySignal 算法。"
        />
        <DecisionStep
          title="4. 信号质量是否放行"
          conclusion={qualityStatusLabel(quality.quality_status)}
          evidence={quality.summary_text_zh || quality.check_summary}
          hint={
            qualityIssues.length > 0
              ? `发现 ${qualityIssues.length} 个质量问题，优先看下方排查区的质量问题明细。`
              : "质量检查没有发现阻断问题；如果仍不合理，应继续看目标仓位映射。"
          }
        />
        <DecisionStep
          title="5. 目标仓位怎么形成"
          conclusion={`目标仓位 ${formatPosition(decision.target_position_ratio ?? period.target_position_ratio)}`}
          evidence={decision.target_reason_summary_zh || decision.evidence_summary}
          hint="如果信号方向和质量都对，但仓位太大或太小，应检查 DecisionSnapshot / position policy。"
        />
      </CardContent>
    </Card>
  );
}

function DecisionStep({
  title,
  conclusion,
  evidence,
  hint
}: {
  title: string;
  conclusion: ReactNode;
  evidence: unknown;
  hint: string;
}) {
  return (
    <section className="rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{title}</h3>
          <div className="mt-1 text-sm">
            结论：<span className="font-medium">{typeof conclusion === "string" ? <NarrativeText value={conclusion} /> : conclusion || "—"}</span>
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <ExplanationBlock title="依据" tone="primary">
          {readableEvidence(evidence)}
        </ExplanationBlock>
        <ExplanationBlock title="排错建议" tone="warning">
          {hint}
        </ExplanationBlock>
      </div>
    </section>
  );
}

function RawEvidenceDetails({
  features,
  atomicSignals,
  domainSignals,
  marketRegime,
  routing,
  signal,
  quality,
  qualityIssues,
  decision
}: {
  features: Array<Record<string, unknown>>;
  atomicSignals: Array<Record<string, unknown>>;
  domainSignals: Array<Record<string, unknown>>;
  marketRegime: Record<string, unknown>;
  routing: Record<string, unknown>;
  signal: Record<string, unknown>;
  quality: Record<string, unknown>;
  qualityIssues: Array<Record<string, unknown>>;
  decision: Record<string, unknown>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>底层明细（排查用）</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Expandable title="FeatureLayer：特征值">
          <SimpleTable
            rows={features}
            columns={[
              { key: "feature_code", label: "特征", render: (row) => featureLabel(row.feature_code) },
              { key: "value", label: "值", render: (row) => featureValue(row) },
              { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
              { key: "evidence", label: "证据", render: (row) => readableEvidence(row.evidence) }
            ]}
          />
        </Expandable>

        <Expandable title="AtomicSignal：原子信号">
          <SimpleTable
            rows={atomicSignals}
            columns={[
              { key: "signal_code", label: "原子", render: (row) => signalLabel(row.signal_code) },
              { key: "direction", label: "方向", render: (row) => directionLabel(row.direction) },
              { key: "strength", label: "强度", render: (row) => formatDecimal(row.strength, 4) },
              { key: "confidence", label: "置信", render: (row) => formatDecimal(row.confidence, 4) },
              { key: "used_feature_codes", label: "使用特征", render: (row) => toStringList(row.used_feature_codes).map(featureLabel).join("、") || "—" },
              { key: "evidence_text_zh", label: "证据", render: (row) => narrativeText(row.evidence_text_zh) }
            ]}
          />
        </Expandable>

        <Expandable title="DomainSignal：领域信号">
          <SimpleTable
            rows={domainSignals}
            columns={[
              { key: "domain_code", label: "领域", render: (row) => domainTitle(row.domain_code) },
              { key: "direction", label: "方向", render: (row) => directionLabel(row.direction) },
              { key: "state_code", label: "状态", render: (row) => stateLabel(row.state_code) },
              { key: "strength", label: "强度", render: (row) => formatDecimal(row.strength, 4) },
              { key: "evidence_text_zh", label: "证据", render: (row) => <NarrativeText value={row.evidence_text_zh} /> }
            ]}
          />
        </Expandable>

        <Expandable title="市场环境 / 策略 / 目标仓位原始对象">
          <div className="grid gap-4 lg:grid-cols-2">
            <RawObject title="MarketRegime" value={marketRegime} />
            <RawObject title="StrategyRouting" value={routing} />
            <RawObject title="StrategySignal" value={signal} />
            <RawObject title="StrategySignalQuality" value={quality} />
            <RawObject title="DecisionSnapshot" value={decision} />
            <RawObject title="质量问题" value={{ issues: qualityIssues }} />
          </div>
        </Expandable>
      </CardContent>
    </Card>
  );
}

function ExplanationBlock({ title, children, tone }: { title: string; children: ReactNode; tone: "primary" | "warning" }) {
  const toneClass =
    tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
      : "border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-100";
  return (
    <div className={`rounded-lg border p-3 text-sm leading-6 ${toneClass}`}>
      <div className="mb-1 font-medium">{title}</div>
      <div>{children}</div>
    </div>
  );
}

function ReviewHint({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">{children}</div>;
}

function Pill({ children }: { children: ReactNode }) {
  return <span className="rounded-full border bg-background px-2 py-1 text-xs font-medium">{children}</span>;
}

function Expandable({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="rounded-xl border bg-muted/10">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium">{title}</summary>
      <div className="border-t p-4">{children}</div>
    </details>
  );
}

function RawObject({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-2 text-sm font-medium">{title}</div>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">
        {compactJson(value)}
      </pre>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  const renderedValue =
    typeof value === "string" || typeof value === "number" || typeof value === "boolean" || value === null || value === undefined
      ? displayValue(value)
      : (value as ReactNode);
  return (
    <div className="min-w-0 rounded-lg border bg-muted/30 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{renderedValue}</div>
    </div>
  );
}

function findByCode(rows: Array<Record<string, unknown>>, key: string, code: unknown): Record<string, unknown> {
  return rows.find((row) => String(row[key] ?? "") === String(code ?? "")) ?? {};
}

function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function domainConclusion(domain: Record<string, unknown>): string {
  if (Object.keys(domain).length === 0) {
    return "无数据";
  }
  return `${directionLabel(domain.direction)}（${stateLabel(domain.state_code)}）`;
}

function ConclusionLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
      <div className="text-muted-foreground">{label}：</div>
      <div className="font-semibold text-foreground">{typeof value === "string" ? <NarrativeText value={value} /> : value}</div>
    </div>
  );
}

function readableEvidence(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") {
    return "没有保存中文依据。";
  }
  return <NarrativeText value={value} />;
}

function narrativeText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const raw = typeof value === "object" ? compactJson(value) : displayValue(value);
  return translateInternalCodes(raw);
}

function NarrativeText({ value }: { value: unknown }) {
  return <>{highlightNarrative(narrativeText(value))}</>;
}

function highlightNarrative(text: string): ReactNode[] {
  const terms = HIGHLIGHT_NARRATIVE_TERMS.map(escapeRegExp).sort((left, right) => right.length - left.length);
  const termPattern = terms.join("|");
  const numberPattern = String.raw`(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z])`;
  const splitPattern = new RegExp(`(${termPattern}|${numberPattern})`, "g");
  const highlightPattern = new RegExp(`^(?:${termPattern}|${numberPattern})$`);

  return text
    .split(splitPattern)
    .filter(Boolean)
    .map((part, index) =>
      highlightPattern.test(part) ? (
        <strong key={`${part}-${index}`} className="font-semibold text-foreground">
          {part}
        </strong>
      ) : (
        part
      )
    );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const HIGHLIGHT_NARRATIVE_TERMS = [
  "大背景偏空",
  "大背景偏多",
  "深度回撤",
  "偏空",
  "偏多",
  "中性",
  "无方向",
  "空头动能增强",
  "空头动能存在",
  "多头动能增强",
  "多头动能存在",
  "动能不明确",
  "波动混合",
  "极端波动",
  "高风险",
  "信号可靠性下降",
  "风险正常",
  "大结构下半部",
  "小结构靠近压力",
  "小结构靠近支撑",
  "小结构不清晰",
  "大结构不清晰",
  "小结构较清晰",
  "空头趋势延续",
  "多头趋势延续",
  "空头背景反弹",
  "多头背景回调",
  "环境不明确",
  "空头趋势跟随",
  "多头趋势跟随",
  "空头反弹压力",
  "多头回调支撑",
  "已选择",
  "无策略",
  "通过",
  "阻断",
  "失败",
  "已形成目标仓位",
  "目标仓位",
  "路由完成",
  "没有形成策略信号"
];

function translateInternalCodes(value: string): string {
  let result = value;
  const replacements: Array<[string, string]> = [
    ["trend_1d_bearish_4h_aligned", "1d 偏空，4h 同向"],
    ["trend_1d_bullish_4h_aligned", "1d 偏多，4h 同向"],
    ["trend_1d_bearish_4h_rebound", "1d 偏空，4h 反弹"],
    ["trend_1d_bullish_4h_pullback", "1d 偏多，4h 回调"],
    ["trend_1d_bearish_4h_unclear", "1d 偏空，4h 不明确"],
    ["trend_1d_bullish_4h_unclear", "1d 偏多，4h 不明确"],
    ["trend_1d_neutral_4h_bullish", "1d 不明确，4h 偏多"],
    ["trend_1d_neutral_4h_bearish", "1d 不明确，4h 偏空"],
    ["trend_unclear", "趋势不明确"],
    ["market_context_deep_drawdown", "深度回撤，大背景偏空"],
    ["market_context_bullish", "大背景偏多"],
    ["market_context_bearish", "大背景偏空"],
    ["momentum_bearish_strengthening", "空头动能增强"],
    ["momentum_bearish_present", "空头动能存在"],
    ["momentum_bearish_exhausting", "空头动能衰竭"],
    ["momentum_bearish_choppy", "空头动能震荡"],
    ["momentum_bullish_strengthening", "多头动能增强"],
    ["momentum_bullish_present", "多头动能存在"],
    ["momentum_bullish_exhausting", "多头动能衰竭"],
    ["momentum_bullish_choppy", "多头动能震荡"],
    ["momentum_neutral_choppy", "震荡动能不清晰"],
    ["momentum_neutral_unclear", "动能不明确"],
    ["volatility_low_compression", "低波动压缩"],
    ["volatility_low", "低波动"],
    ["volatility_normal", "正常波动"],
    ["volatility_high", "高波动"],
    ["volatility_mixed", "波动混合"],
    ["volatility_extreme", "极端波动"],
    ["risk_high_signal_unreliable", "高风险，信号可靠性下降"],
    ["risk_elevated_classifiable", "风险升高，但仍可分类"],
    ["risk_unclear", "风险不明确"],
    ["risk_clear", "风险正常"],
    ["structure_major_lower_half_minor_near_resistance", "大结构下半部，小结构靠近压力"],
    ["structure_major_lower_half_minor_unclear", "大结构下半部，小结构不清晰"],
    ["structure_major_unclear_minor_clear", "大结构不清晰，小结构较清晰"],
    ["structure_major_near_resistance_minor_unclear", "大结构靠近压力，小结构不清晰"],
    ["structure_major_near_support_minor_unclear", "大结构靠近支撑，小结构不清晰"],
    ["structure_major_near_resistance_minor_aligned", "大结构靠近压力，小结构同样靠近压力"],
    ["structure_major_near_support_minor_aligned", "大结构靠近支撑，小结构同样靠近支撑"],
    ["structure_major_range_middle_minor_range_middle", "大结构区间中部，小结构区间中部"],
    ["structure_major_range_middle_minor_near_resistance", "大结构区间中部，小结构靠近压力"],
    ["structure_major_range_middle_minor_near_support", "大结构区间中部，小结构靠近支撑"],
    ["structure_unclear", "结构不明确"],
    ["structure_major_conflicted", "大结构冲突"],
    ["structure_conflicted", "结构冲突"],
    ["bearish_trend_continuation", "空头趋势延续"],
    ["bullish_trend_continuation", "多头趋势延续"],
    ["bearish_rebound_environment", "空头背景反弹"],
    ["bullish_pullback_environment", "多头背景回调"],
    ["high_risk_environment", "高风险环境"],
    ["unclear_environment", "环境不明确"],
    ["short_trend_following", "空头趋势跟随"],
    ["long_trend_following", "多头趋势跟随"],
    ["short_rebound_pressure", "空头反弹压力"],
    ["strategy_route_decision_created", "路由完成，但没有形成策略信号"],
    ["decision_snapshot_created", "已形成目标仓位"],
    ["market_context", "市场大背景"],
    ["risk_state", "风险状态"],
    ["domain_signal", "领域信号"],
    ["atomic_signal", "原子信号"]
  ];
  for (const [code, label] of replacements) {
    result = result.replaceAll(code, label);
  }
  const wordReplacements: Array<[RegExp, string]> = [
    [/\bbearish\b/g, "偏空"],
    [/\bbullish\b/g, "偏多"],
    [/\bneutral\b/g, "中性"],
    [/\bnone\b/g, "无方向"],
    [/\bselected\b/g, "已选择"],
    [/\bno_strategy\b/g, "无策略"],
    [/\bpassed\b/g, "通过"],
    [/\bblocked\b/g, "阻断"],
    [/\bfailed\b/g, "失败"]
  ];
  for (const [pattern, label] of wordReplacements) {
    result = result.replace(pattern, label);
  }
  return result;
}

function featureValue(row: Record<string, unknown>): string {
  if (row.numeric_value !== null && row.numeric_value !== undefined && row.numeric_value !== "") {
    return formatDecimal(row.numeric_value, 6);
  }
  if (row.bool_value !== null && row.bool_value !== undefined && row.bool_value !== "") {
    return displayValue(row.bool_value);
  }
  if (row.text_value !== null && row.text_value !== undefined && row.text_value !== "") {
    return displayValue(row.text_value);
  }
  return compactJson(row.value_json);
}

function compactJson(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value !== "object") {
    return displayValue(value);
  }
  return JSON.stringify(value, null, 2);
}

function formatDecimal(value: unknown, digits = 2): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  });
}

function formatUtcMinute(value: unknown): string {
  const text = String(value ?? "");
  if (!text) {
    return "—";
  }
  const minute = text.slice(0, 16).replace("T", " ");
  return minute || "—";
}

function formatPercent(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  return `${(number * 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}%`;
}

function formatPosition(value: unknown): string {
  return formatPercent(value);
}

function ReturnPercent({ value }: { value: unknown }) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return <span className="text-muted-foreground">—</span>;
  }
  const text = `${(number * 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}%`;
  if (number > 0) {
    return <span className="font-medium text-emerald-600 dark:text-emerald-400">+{text}</span>;
  }
  if (number < 0) {
    return <span className="font-medium text-red-600 dark:text-red-400">{text}</span>;
  }
  return <span>{text}</span>;
}

function domainTitle(value: unknown): string {
  const labels: Record<string, string> = {
    market_context: "市场大背景",
    trend: "趋势",
    momentum: "动能",
    volatility: "波动",
    structure: "结构位置",
    risk_state: "风险状态"
  };
  const text = String(value ?? "");
  return labels[text] ?? humanizeCode(text);
}

function directionLabel(value: unknown): string {
  const labels: Record<string, string> = {
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    none: "无方向"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function stateLabel(value: unknown): string {
  const labels: Record<string, string> = {
    market_context_deep_drawdown: "深度回撤，大背景偏空",
    market_context_bullish: "大背景偏多",
    market_context_bearish: "大背景偏空",
    trend_1d_bearish_4h_aligned: "1d 偏空，4h 同向",
    trend_1d_bullish_4h_aligned: "1d 偏多，4h 同向",
    trend_1d_bearish_4h_rebound: "1d 偏空，4h 反弹",
    trend_1d_bullish_4h_pullback: "1d 偏多，4h 回调",
    trend_1d_bearish_4h_unclear: "1d 偏空，4h 不明确",
    trend_1d_bullish_4h_unclear: "1d 偏多，4h 不明确",
    trend_1d_neutral_4h_bullish: "1d 不明确，4h 偏多",
    trend_1d_neutral_4h_bearish: "1d 不明确，4h 偏空",
    trend_unclear: "趋势不明确",
    momentum_bearish_strengthening: "空头动能增强",
    momentum_bearish_present: "空头动能存在",
    momentum_bearish_exhausting: "空头动能衰竭",
    momentum_bearish_choppy: "空头动能震荡",
    momentum_bullish_strengthening: "多头动能增强",
    momentum_bullish_present: "多头动能存在",
    momentum_bullish_exhausting: "多头动能衰竭",
    momentum_bullish_choppy: "多头动能震荡",
    momentum_neutral_choppy: "震荡动能不清晰",
    momentum_neutral_unclear: "动能不明确",
    volatility_low_compression: "低波动压缩",
    volatility_low: "低波动",
    volatility_normal: "正常波动",
    volatility_high: "高波动",
    volatility_mixed: "波动混合",
    volatility_extreme: "极端波动",
    risk_clear: "风险正常",
    risk_elevated_classifiable: "风险升高，但仍可分类",
    risk_unclear: "风险不明确",
    risk_high_signal_unreliable: "高风险，信号可靠性下降",
    structure_major_lower_half_minor_unclear: "大结构下半部，小结构不清晰",
    structure_major_lower_half_minor_near_resistance: "大结构下半部，小结构靠近压力",
    structure_major_unclear_minor_clear: "大结构不清晰，小结构较清晰",
    structure_major_near_resistance_minor_unclear: "大结构靠近压力，小结构不清晰",
    structure_major_near_support_minor_unclear: "大结构靠近支撑，小结构不清晰",
    structure_major_near_resistance_minor_aligned: "大结构靠近压力，小结构同样靠近压力",
    structure_major_near_support_minor_aligned: "大结构靠近支撑，小结构同样靠近支撑",
    structure_major_range_middle_minor_range_middle: "大结构区间中部，小结构区间中部",
    structure_major_range_middle_minor_near_resistance: "大结构区间中部，小结构靠近压力",
    structure_major_range_middle_minor_near_support: "大结构区间中部，小结构靠近支撑",
    structure_major_lower_half_minor_range_observed: "大结构下半部，小结构观察到区间",
    structure_major_upper_half_minor_range_observed: "大结构上半部，小结构观察到区间",
    structure_major_lower_half_minor_conflicted: "大结构下半部，小结构冲突",
    structure_major_upper_half_minor_conflicted: "大结构上半部，小结构冲突",
    structure_major_conflicted: "大结构冲突",
    structure_conflicted: "结构冲突",
    structure_unclear: "结构不明确"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function regimeLabel(value: unknown): string {
  const labels: Record<string, string> = {
    unclear_environment: "环境不明确",
    bearish_trend_continuation: "空头趋势延续",
    high_risk_environment: "高风险环境",
    bullish_trend_continuation: "多头趋势延续",
    bearish_rebound_environment: "空头背景反弹",
    bullish_pullback_environment: "多头背景回调"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function routeOutcomeLabel(value: unknown): string {
  const labels: Record<string, string> = {
    selected: "已选择策略",
    no_strategy: "无策略",
    blocked: "阻断",
    failed: "失败"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function qualityStatusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    passed: "通过",
    warning: "有警告",
    blocked: "阻断",
    failed: "失败"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function reasonLabel(value: unknown): string {
  const labels: Record<string, string> = {
    strategy_route_decision_created: "路由完成，但没有形成策略信号",
    decision_snapshot_created: "已形成目标仓位",
    strategy_backtest_completed: "回测完成"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function strategyLabel(value: unknown): string {
  const labels: Record<string, string> = {
    short_trend_following: "空头趋势跟随",
    long_trend_following: "多头趋势跟随",
    short_rebound_pressure: "空头反弹压力"
  };
  const text = String(value ?? "");
  return labels[text] ?? (text ? humanizeCode(text) : "—");
}

function featureLabel(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    latest_close_1d: "1d 最新收盘价",
    latest_close_4h: "4h 最新收盘价",
    drawdown_from_high_pct_1d_365: "近 365 日高点回撤",
    drawdown_duration_days_1d_365: "近 365 日回撤持续天数",
    rebound_from_drawdown_low_pct_1d_365: "从回撤低点反弹幅度",
    recovery_ratio_from_drawdown_1d_365: "回撤收复比例",
    close_vs_sma_pct_1d_200: "1d 收盘价相对 200 日均线距离",
    close_vs_sma_pct_1d_365: "1d 收盘价相对 365 日均线距离",
    atr_percentile_1d_120: "1d ATR 历史分位",
    atr_percentile_4h_120: "4h ATR 历史分位"
  };
  return labels[text] ?? humanizeCode(text);
}

function signalLabel(value: unknown): string {
  const text = String(value ?? "");
  return humanizeCode(translateInternalCodes(text));
}

function humanizeCode(value: string): string {
  if (!value) {
    return "—";
  }
  let text = value.replaceAll("_", " ");
  const replacements: Array<[string, string]> = [
    ["market context", "市场大背景"],
    ["price above sma", "价格高于均线"],
    ["price below sma", "价格低于均线"],
    ["sma rising", "均线上行"],
    ["sma falling", "均线下行"],
    ["deep drawdown", "深度回撤"],
    ["moderate drawdown", "中等回撤"],
    ["from 365d high", "距离 365 日高点"],
    ["high recovery", "高收复"],
    ["low recovery", "低收复"],
    ["material rebound", "明显反弹"],
    ["trend 1d", "1d 趋势"],
    ["trend 4h", "4h 趋势"],
    ["ma bearish alignment", "均线空头排列"],
    ["ma bullish alignment", "均线多头排列"],
    ["atr high percentile", "ATR 高分位"],
    ["atr low percentile", "ATR 低分位"],
    ["atr extreme percentile", "ATR 极端分位"],
    ["near resistance", "靠近压力"],
    ["near support", "靠近支撑"]
  ];
  for (const [from, to] of replacements) {
    text = text.replaceAll(from, to);
  }
  return text;
}
