import Link from "next/link";
import { redirect } from "next/navigation";
import { Eye } from "lucide-react";

import { ApiError } from "@/components/ops/api-error";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRows } from "@/lib/ops-data";

import { StrategyBacktestForm } from "./backtest-form";

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function StrategyBacktestsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const selectedRunId = firstParam(params.run_id) ?? "";
  if (selectedRunId) {
    redirect(`/strategy-backtests/${encodeURIComponent(selectedRunId)}`);
  }

  const releasesResult = await opsFetch<Paginated<Record<string, unknown>>>("/api/ops/strategy-releases/?limit=100");
  const runsResult = await opsFetch<Paginated<Record<string, unknown>>>("/api/ops/strategy-backtests/runs/?limit=20");

  if (!releasesResult.ok) {
    return <ApiError reason={releasesResult.reason_code} message={releasesResult.message_zh} />;
  }
  if (!runsResult.ok) {
    return <ApiError reason={runsResult.reason_code} message={runsResult.message_zh} />;
  }

  const releases = asRows(releasesResult.data.items);
  const runs = asRows(runsResult.data.items);

  return (
    <>
      <PageHeader
        title="策略回测"
        description="创建测试环境回测任务，并从历史运行列表进入单次回测详情；本页不展示具体调仓明细。"
      />

      <Card className="mb-6">
        <CardContent className="pt-6 text-sm text-muted-foreground">
          当前 P0 口径：页面按 UTC 日期选择范围，每个日期会转换为当天 00:00 的 4h 边界；回测内部仍逐个 UTC 4h
          周期计算收益。具体收益摘要和模拟调仓明细请进入某次回测详情页查看。
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <StrategyBacktestForm releases={releases} />

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>最近回测运行</CardTitle>
          </CardHeader>
          <CardContent className="min-w-0">
            <SimpleTable
              rows={runs}
              columns={[
                {
                  key: "id",
                  label: "ID",
                  render: (row) => (
                    <Link className="font-medium underline" href={`/strategy-backtests/${row.id}`}>
                      {String(row.id)}
                    </Link>
                  )
                },
                {
                  key: "status",
                  label: "状态",
                  render: (row) => (
                    <div title={String(row.diagnostic_message_zh ?? "") || undefined}>
                      <StatusBadge value={displayStatus(row)} />
                    </div>
                  )
                },
                { key: "progress", label: "进度", render: (row) => progressText(row) },
                { key: "release_display_name", label: "版本包" },
                { key: "total_return_pct", label: "本次收益", render: (row) => <ReturnPercent value={row.total_return_pct} /> },
                { key: "start_analysis_close_time_utc", label: "开始", render: (row) => formatUtcDate(row.start_analysis_close_time_utc) },
                { key: "end_analysis_close_time_utc", label: "结束", render: (row) => formatUtcDate(row.end_analysis_close_time_utc) },
                {
                  key: "detail",
                  label: "操作",
                  render: (row) => (
                    <Link
                      className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-sm font-medium text-foreground hover:bg-muted"
                      href={`/strategy-backtests/${row.id}`}
                    >
                      <Eye className="h-4 w-4" />
                      详情
                    </Link>
                  )
                },
              ]}
            />
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function progressText(row: Record<string, unknown>): string {
  const completed = Number(row.progress_completed_periods ?? 0);
  const total = Number(row.progress_total_periods ?? 0);
  if (total <= 0) {
    return "—";
  }
  const percent = Math.min(100, Math.round((completed / total) * 100));
  return `${completed}/${total}（${percent}%）`;
}

function displayStatus(row: Record<string, unknown>): unknown {
  return row.diagnostic_status || row.status;
}

function formatUtcDate(value: unknown): string {
  const text = String(value ?? "");
  if (!text) {
    return "—";
  }
  return text.slice(0, 10) || "—";
}

function ReturnPercent({ value }: { value: unknown }) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return <span className="text-muted-foreground">—</span>;
  }
  const prefix = number > 0 ? "+" : "";
  const text = `${prefix}${(number * 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}%`;
  if (number > 0) {
    return <span className="font-medium text-emerald-600 dark:text-emerald-400">{text}</span>;
  }
  if (number < 0) {
    return <span className="font-medium text-red-600 dark:text-red-400">{text}</span>;
  }
  return <span>{text}</span>;
}

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
