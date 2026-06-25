import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { FilterBar } from "@/components/ops/filter-bar";
import { JsonBlock } from "@/components/ops/json-block";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatCard } from "@/components/ops/stat-card";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRecord, asRows } from "@/lib/ops-data";
import { displayValue, formatUtc, toSearchParams } from "@/lib/utils";

import { PerformanceBackfillForm } from "./backfill-form";
import { PerformancePnlChart } from "./performance-pnl-chart";

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function previewReasonRows(preview: Record<string, unknown>) {
  return Object.entries(asRecord(preview.not_calculable_reason_counts)).map(([reason_code, count]) => ({
    reason_code,
    count
  }));
}

export default async function PerformancePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const [recordsResult, previewResult] = await Promise.all([
    opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/performance/${toSearchParams(params)}`),
    opsFetch<Record<string, unknown>>("/api/ops/performance/preview/")
  ]);

  if (!recordsResult.ok) {
    return <ApiError reason={recordsResult.reason_code} message={recordsResult.message_zh} />;
  }

  const rows = asRows(recordsResult.data.items);
  const pagination = asRecord(recordsResult.data.pagination);
  const preview = previewResult.ok
    ? previewResult.data
    : {
        scanned_period_count: "—",
        existing_period_count: "—",
        missing_period_count: "—",
        calculable_missing_period_count: "—",
        not_calculable_reason_counts: {
          [previewResult.reason_code]: previewResult.message_zh
        },
        items: []
      };
  const previewItems = asRows(preview.items);
  const reasonRows = previewReasonRows(preview);

  return (
    <>
      <PageHeader
        title="Performance"
        description="展示 PerformanceMetrics 已落库结果，并提供后台一键补算入口；本页不自行计算周期收益。"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="绩效记录总数" value={String(pagination.total ?? rows.length)} helper="来自 OrchestrationRunPerformance" />
        <StatCard label="已扫描周期" value={String(preview.scanned_period_count ?? "—")} helper="预览不写库" />
        <StatCard label="缺失周期" value={String(preview.missing_period_count ?? "—")} helper="不等于主链路异常" />
        <StatCard label="可补算周期" value={String(preview.calculable_missing_period_count ?? "—")} helper="由后端 service 判定" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader>
            <CardTitle>周期浮动收益曲线</CardTitle>
            <CardDescription>只绘制后端已计算的 cycle_floating_pnl；不使用订单 realized PnL 替代周期收益。</CardDescription>
          </CardHeader>
          <CardContent>
            <PerformancePnlChart rows={rows} />
          </CardContent>
        </Card>
        <PerformanceBackfillForm preview={preview} />
      </div>

      <section className="mt-6">
        <h2 className="mb-3 text-lg font-semibold">绩效记录</h2>
        <FilterBar
          fields={[
            {
              type: "select",
              name: "calculation_status",
              label: "计算状态",
              defaultValue: String(params.calculation_status ?? ""),
              options: [
                { label: "全部", value: "" },
                { label: "calculated", value: "calculated" },
                { label: "insufficient_snapshot", value: "insufficient_snapshot" },
                { label: "skipped", value: "skipped" },
                { label: "failed", value: "failed" }
              ]
            },
            { type: "input", name: "market_type", label: "市场类型", placeholder: "USDS-M / COIN-M", defaultValue: String(params.market_type ?? "") },
            { type: "input", name: "account_domain", label: "账户域", defaultValue: String(params.account_domain ?? "") },
            { type: "input", name: "symbol", label: "symbol", placeholder: "BTCUSDT", defaultValue: String(params.symbol ?? "") },
            { type: "input", name: "reason_code", label: "reason_code", defaultValue: String(params.reason_code ?? "") },
            {
              type: "select",
              name: "limit",
              label: "数量",
              defaultValue: String(params.limit ?? "20"),
              options: [
                { label: "20", value: "20" },
                { label: "50", value: "50" },
                { label: "100", value: "100" }
              ]
            }
          ]}
        />
        <div className="mb-3 text-sm text-muted-foreground">共 {String(pagination.total ?? rows.length)} 条</div>
        {rows.length === 0 ? (
          <EmptyState title="暂无绩效记录" description="可以先查看缺失周期预览；如存在可补算周期，再通过后台一键补算生成记录。" />
        ) : (
          <SimpleTable
            rows={rows}
            columns={[
              { key: "period_end_utc", label: "周期结束", render: (row) => formatUtc(row.period_end_utc) },
              { key: "period_start_utc", label: "周期开始", render: (row) => formatUtc(row.period_start_utc) },
              { key: "calculation_status", label: "状态", render: (row) => <StatusBadge value={row.calculation_status} /> },
              { key: "cycle_floating_pnl", label: "周期浮动收益" },
              { key: "cycle_floating_pnl_pct", label: "周期收益率" },
              { key: "net_fill_quantity", label: "本周期净调仓" },
              { key: "order_realized_pnl", label: "订单 realized PnL" },
              { key: "order_commission", label: "手续费" },
              { key: "symbol", label: "symbol" },
              { key: "market_type", label: "市场" },
              { key: "account_domain", label: "账户域" },
              {
                key: "start_orchestration_run_id",
                label: "开始 run",
                render: (row) =>
                  row.start_orchestration_run_id ? (
                    <Link className="font-medium underline" href={`/runs/${row.start_orchestration_run_id}`}>
                      {String(row.start_orchestration_run_id)}
                    </Link>
                  ) : (
                    displayValue(row.start_orchestration_run_id)
                  )
              },
              {
                key: "end_orchestration_run_id",
                label: "结束 run",
                render: (row) =>
                  row.end_orchestration_run_id ? (
                    <Link className="font-medium underline" href={`/runs/${row.end_orchestration_run_id}`}>
                      {String(row.end_orchestration_run_id)}
                    </Link>
                  ) : (
                    displayValue(row.end_orchestration_run_id)
                  )
              },
              { key: "has_order_submission", label: "有订单提交" },
              { key: "has_fill", label: "有成交" },
              { key: "reason_code", label: "原因" }
            ]}
          />
        )}
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <section>
          <h2 className="mb-3 text-lg font-semibold">缺失周期预览</h2>
          {previewItems.length === 0 ? (
            <EmptyState title="暂无可展示的预览周期" description="预览只读取后端扫描结果，不写入绩效记录。" />
          ) : (
            <SimpleTable
              rows={previewItems}
              columns={[
                { key: "period_start_utc", label: "周期开始", render: (row) => formatUtc(row.period_start_utc) },
                { key: "period_end_utc", label: "周期结束", render: (row) => formatUtc(row.period_end_utc) },
                { key: "calculable", label: "可补算" },
                { key: "already_exists", label: "已存在" },
                { key: "market_type", label: "市场" },
                { key: "account_domain", label: "账户域" },
                { key: "symbol", label: "symbol" },
                { key: "reason_code", label: "原因" }
              ]}
            />
          )}
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">不可计算原因摘要</h2>
          {reasonRows.length === 0 ? (
            <EmptyState title="暂无不可计算原因" description="当前预览中没有发现缺失且不可计算的周期。" />
          ) : (
            <SimpleTable
              rows={reasonRows}
              columns={[
                { key: "reason_code", label: "reason_code" },
                { key: "count", label: "数量" }
              ]}
            />
          )}
          {!previewResult.ok ? (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle>预览接口异常</CardTitle>
              </CardHeader>
              <CardContent>
                <JsonBlock value={preview} />
              </CardContent>
            </Card>
          ) : null}
        </section>
      </div>
    </>
  );
}
