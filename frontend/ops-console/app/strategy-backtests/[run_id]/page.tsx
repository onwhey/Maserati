import Link from "next/link";
import type { ReactNode } from "react";

import { ApiError } from "@/components/ops/api-error";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRecord, asRows } from "@/lib/ops-data";
import { displayValue, formatUtc } from "@/lib/utils";

import { BacktestAutoRefresh } from "../auto-refresh";

type PageProps = {
  params: Promise<{ run_id: string }>;
};

export default async function StrategyBacktestDetailPage({ params }: PageProps) {
  const { run_id: runId } = await params;
  const detailResult = await opsFetch<Record<string, unknown>>(
    `/api/ops/strategy-backtests/runs/${encodeURIComponent(runId)}/`
  );
  const periodsResult = await opsFetch<Paginated<Record<string, unknown>>>(
    `/api/ops/strategy-backtests/runs/${encodeURIComponent(runId)}/periods/?limit=500`
  );

  if (!detailResult.ok) {
    return <ApiError reason={detailResult.reason_code} message={detailResult.message_zh} />;
  }
  if (!periodsResult.ok) {
    return <ApiError reason={periodsResult.reason_code} message={periodsResult.message_zh} />;
  }

  const runDetail = detailResult.data;
  const selectedRun = asRecord(runDetail.run);
  const resultSummary = asRecord(runDetail.result_summary);
  const periodRows = asRows(periodsResult.data.items);
  const periodPagination = periodsResult.data.pagination;
  const selectedStatus = String(selectedRun.status ?? "");
  const diagnosticStatus = String(selectedRun.diagnostic_status ?? "");
  const shouldRefresh = !diagnosticStatus && (selectedStatus === "queued" || selectedStatus === "running");
  const progressCompleted = Number(selectedRun.progress_completed_periods ?? 0);
  const progressTotal = Number(selectedRun.progress_total_periods ?? 0);
  const progressPercent = progressTotal > 0 ? Math.min(100, Math.round((progressCompleted / progressTotal) * 100)) : 0;

  return (
    <>
      <BacktestAutoRefresh enabled={shouldRefresh} />
      <PageHeader
        title={`回测详情 #${displayValue(selectedRun.id)}`}
        description="查看单次回测的运行状态、收益摘要和每个 UTC 4h 周期的模拟调仓明细。"
      />

      <div className="mb-4">
        <Link className="text-sm underline text-muted-foreground hover:text-foreground" href="/strategy-backtests">
          返回策略回测列表
        </Link>
      </div>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>运行状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Metric label="状态" value={<StatusBadge value={diagnosticStatus || selectedRun.status} />} />
              <Metric label="原因" value={reasonLabel(selectedRun.reason_code)} />
              <Metric label="任务 ID" value={compactId(selectedRun.celery_task_id)} />
              <Metric label="进度" value={progressTotal > 0 ? `${progressCompleted} / ${progressTotal}（${progressPercent}%）` : "—"} />
              <Metric label="当前处理边界" value={formatUtcDate(selectedRun.progress_current_analysis_close_time_utc)} />
              <Metric label="开始边界" value={formatUtcDate(selectedRun.start_analysis_close_time_utc)} />
              <Metric label="结束边界" value={formatUtcDate(selectedRun.end_analysis_close_time_utc)} />
            </div>

            {progressTotal > 0 ? (
              <div className="space-y-2">
                <div className="h-3 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progressPercent}%` }} />
                </div>
                <div className="text-xs text-muted-foreground">
                  最近周期：{statusText(selectedRun.progress_last_status)} / {reasonLabel(selectedRun.progress_last_reason_code)}
                </div>
              </div>
            ) : null}

            {shouldRefresh ? (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
                后台任务还没结束，本页会每 5 秒自动刷新；你也可以直接刷新页面，任务状态不会丢。
              </div>
            ) : null}

            {diagnosticStatus ? (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
                {displayValue(selectedRun.diagnostic_message_zh)}
              </div>
            ) : null}

            {selectedRun.error_message ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {String(selectedRun.error_message)}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>收益摘要</CardTitle>
          </CardHeader>
          <CardContent>
            {Object.keys(resultSummary).length > 0 ? (
              <BacktestResult result={resultSummary} />
            ) : (
              <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
                当前运行还没有结果摘要。排队或运行中时请等待后台任务完成；如果长时间停在排队中，需要确认 Celery worker 是否已启动。
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>模拟调仓明细</CardTitle>
          </CardHeader>
          <CardContent>
            <BacktestPeriodTable
              periods={periodRows}
              total={Number(periodPagination.total ?? 0)}
              isFinished={!shouldRefresh && Object.keys(resultSummary).length > 0}
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function BacktestResult({ result }: { result: Record<string, unknown> }) {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="初始资金" value={formatDecimal(result.initial_equity, 2)} />
        <Metric label="杠杆倍数" value={formatDecimal(result.leverage, 2)} />
        <Metric label="结束资金" value={formatDecimal(result.final_equity, 2)} />
        <Metric label="总收益率" value={formatPercent(result.total_return_pct)} />
        <Metric label="最大回撤" value={formatPercent(result.max_drawdown_pct)} />
        <Metric label="模拟调仓次数" value={result.trade_count} />
        <Metric label="买入持有对照" value={formatPercent(result.benchmark_buy_hold_return_pct)} />
        <Metric label="完成周期" value={result.completed_count} />
        <Metric label="无法模拟周期" value={result.simulation_blocked_count} />
        <Metric label="是否爆仓" value={result.is_liquidated ? "是" : "否"} />
        <Metric label="爆仓周期" value={result.is_liquidated ? result.liquidation_period_index : "—"} />
        <Metric label="爆仓时间" value={result.is_liquidated ? formatUtc(result.liquidation_analysis_close_time_utc) : "—"} />
        <Metric label="估算强平价" value={result.is_liquidated ? formatDecimal(result.liquidation_price, 2) : "—"} />
        <Metric label="已计算周期" value={result.stored_period_count} />
        <Metric label="手续费合计" value={formatDecimal(result.total_fee, 4)} />
      </div>

      <div>
        <div className="mb-2 text-sm font-medium">策略出现次数</div>
        <StrategyCounts value={result.strategy_counts} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <PeriodSummary title="第一周期" value={asRecord(result.first_period)} />
        <PeriodSummary title="最后周期" value={asRecord(result.last_period)} />
      </div>
    </div>
  );
}

function BacktestPeriodTable({
  periods,
  total,
  isFinished
}: {
  periods: Array<Record<string, unknown>>;
  total: number;
  isFinished: boolean;
}) {
  if (periods.length === 0) {
    return isFinished ? (
      <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
        当前回测记录没有周期明细。旧记录是在明细落库前生成的，需要重新跑一次回测后才能看到每个周期的调仓价格和仓位变化。
      </div>
    ) : (
      <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">任务完成后这里会显示周期明细。</div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        模拟成交价按该 UTC 4h 周期的开盘价计算，不是真实交易所订单价；仓位变化为目标仓位相对上一周期仓位的变化。
        {total > periods.length ? ` 当前展示前 ${periods.length} 条，共 ${total} 条。` : ""}
      </div>
      <SimpleTable
        rows={periods}
        columns={[
          { key: "period_index", label: "序号" },
          { key: "analysis_close_time_utc", label: "UTC 周期", render: (row) => formatUtc(row.analysis_close_time_utc) },
          { key: "status", label: "状态", render: (row) => statusText(row.status) },
          { key: "period_return_pct", label: "周期收益", render: (row) => <ReturnPercent value={row.period_return_pct} /> },
          { key: "selected_strategy", label: "策略", render: (row) => strategyLabel(row.selected_strategy) },
          { key: "signal_direction", label: "方向", render: (row) => directionLabel(row.signal_direction) },
          { key: "previous_position_ratio", label: "调仓前", render: (row) => formatPosition(row.previous_position_ratio) },
          { key: "target_position_ratio", label: "目标仓位", render: (row) => formatPosition(row.target_position_ratio) },
          { key: "effective_position_ratio", label: "有效仓位", render: (row) => formatPosition(row.effective_position_ratio) },
          { key: "position_change_ratio", label: "仓位变化", render: (row) => positionChangeText(row.position_change_ratio) },
          { key: "effective_position_change_ratio", label: "有效变化", render: (row) => positionChangeText(row.effective_position_change_ratio) },
          { key: "position_change_notional", label: "变化金额", render: (row) => signedDecimal(row.position_change_notional, 2) },
          { key: "effective_position_notional", label: "有效名义金额", render: (row) => signedDecimal(row.effective_position_notional, 2) },
          { key: "simulated_execution_price", label: "模拟成交价", render: (row) => formatDecimal(row.simulated_execution_price, 2) },
          { key: "close_price", label: "收盘价", render: (row) => formatDecimal(row.close_price, 2) },
          { key: "liquidation_price", label: "估算强平价", render: (row) => formatDecimal(row.liquidation_price, 2) },
          { key: "kline_return_pct", label: "K线涨跌", render: (row) => formatPercent(row.kline_return_pct) },
          { key: "fee", label: "手续费", render: (row) => formatDecimal(row.fee, 4) },
          { key: "equity", label: "权益", render: (row) => formatDecimal(row.equity, 2) },
          { key: "reason_code", label: "原因", render: (row) => reasonLabel(row.reason_code) },
        ]}
      />
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

function StrategyCounts({ value }: { value: unknown }) {
  const counts = asRecord(value);
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">没有策略命中。</div>;
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      {entries.map(([strategy, count]) => (
        <div key={strategy} className="flex items-center justify-between gap-4 border-b px-4 py-2 text-sm last:border-b-0">
          <span className="break-words">{strategyLabel(strategy)}</span>
          <span className="font-medium">{displayValue(count)}</span>
        </div>
      ))}
    </div>
  );
}

function PeriodSummary({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div>
      <div className="mb-2 text-sm font-medium">{title}</div>
      <div className="grid gap-2 rounded-lg border bg-muted/20 p-3 text-sm">
        <SummaryRow label="时间" value={formatUtc(value.analysis_close_time_utc)} />
        <SummaryRow label="状态" value={statusText(value.status)} />
        <SummaryRow label="原因" value={reasonLabel(value.reason_code)} />
        <SummaryRow label="爆仓" value={value.is_liquidated ? "是" : "否"} />
        <SummaryRow label="估算强平价" value={formatDecimal(value.liquidation_price, 2)} />
        <SummaryRow label="市场环境" value={regimeLabel(value.market_regime)} />
        <SummaryRow label="策略" value={strategyLabel(value.selected_strategy)} />
        <SummaryRow label="方向" value={directionLabel(value.signal_direction)} />
        <SummaryRow label="目标仓位" value={formatPosition(value.target_position_ratio)} />
        <SummaryRow label="有效仓位" value={formatPosition(value.effective_position_ratio)} />
        <SummaryRow label="实际仓位" value={formatPosition(value.position_ratio)} />
        <SummaryRow label="开盘 / 收盘" value={`${formatDecimal(value.open_price, 2)} / ${formatDecimal(value.close_price, 2)}`} />
        <SummaryRow label="K线涨跌" value={formatPercent(value.kline_return_pct)} />
        <SummaryRow label="周期收益" value={formatPercent(value.period_return_pct)} />
        <SummaryRow label="回撤" value={formatPercent(value.drawdown_pct)} />
        <SummaryRow label="手续费" value={formatDecimal(value.fee, 4)} />
        <SummaryRow label="权益" value={formatDecimal(value.equity, 2)} />
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="grid grid-cols-[92px_1fr] gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words font-medium">{displayValue(value)}</span>
    </div>
  );
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

function formatUtcDate(value: unknown): string {
  const text = String(value ?? "");
  if (!text) {
    return "—";
  }
  return text.slice(0, 10) || "—";
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

function formatPosition(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  return `${(number * 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  })}%`;
}

function positionChangeText(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  if (number === 0) {
    return "不变";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${(number * 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  })}%`;
}

function signedDecimal(value: unknown, digits = 2): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  if (number === 0) {
    return "0";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits
  })}`;
}

function reasonLabel(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    strategy_backtest_completed: "回测完成",
    strategy_backtest_completed_liquidated: "回测完成，期间发生爆仓",
    strategy_backtest_completed_with_blocked_period: "回测完成，但存在无法模拟周期",
    strategy_backtest_running: "正在运行",
    running_completed_without_result: "周期完成但结果未写入，疑似卡住",
    running_progress_stale: "长时间没有进度更新，疑似卡住",
    strategy_backtest_queued: "等待后台执行",
    strategy_backtest_run_created: "已创建后台任务",
    strategy_route_decision_created: "没有目标仓位或未选择策略",
    decision_snapshot_created: "已生成目标仓位",
    execution_kline_missing: "缺少用于收益模拟的 4h K线",
    quality_issues_found: "数据质量检查未通过",
    long_liquidation_intraperiod: "多头周期内触发估算强平",
    short_liquidation_intraperiod: "空头周期内触发估算强平",
    liquidation_by_fee: "手续费导致权益不足",
    liquidation_by_equity_depletion: "周期结算权益归零"
  };
  return (labels[text] ?? text) || "—";
}

function statusText(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    completed: "已完成",
    completed_no_strategy: "已完成，无策略",
    liquidated: "已爆仓",
    blocked: "阻断",
    running: "运行中",
    queued: "排队中",
    succeeded: "已完成",
    failed: "失败"
  };
  return (labels[text] ?? text) || "—";
}

function directionLabel(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    none: "无方向"
  };
  return (labels[text] ?? text) || "—";
}

function regimeLabel(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    unclear_environment: "环境不明确",
    bearish_trend_continuation: "空头趋势延续",
    high_risk_environment: "高风险环境",
    bullish_trend_continuation: "多头趋势延续",
    bearish_rebound_environment: "空头背景反弹",
    bullish_pullback_environment: "多头背景回调"
  };
  return (labels[text] ?? text) || "—";
}

function strategyLabel(value: unknown): string {
  const text = String(value ?? "");
  const labels: Record<string, string> = {
    short_trend_following: "空头趋势跟随",
    long_trend_following: "多头趋势跟随",
    short_rebound_pressure: "空头反弹压力"
  };
  return (labels[text] ?? text) || "—";
}

function compactId(value: unknown): string {
  const text = String(value ?? "");
  if (text.length <= 18) {
    return text || "—";
  }
  return `${text.slice(0, 8)}…${text.slice(-6)}`;
}
