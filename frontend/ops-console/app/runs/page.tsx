import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { FilterBar } from "@/components/ops/filter-bar";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc, toSearchParams } from "@/lib/utils";

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function RunsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/runs/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const pagination = asRecord(result.data.pagination);
  const rows = asRows(result.data.items);

  return (
    <>
      <PageHeader title="Runs" description="查看自动与人工诊断编排事实；本页只导航和展示，不创建、不重跑、不推进编排。" />
      <FilterBar
        fields={[
          {
            type: "select",
            name: "status",
            label: "状态",
            defaultValue: String(params.status ?? ""),
            options: [
              { label: "全部", value: "" },
              { label: "running", value: "running" },
              { label: "completed", value: "completed" },
              { label: "completed_no_action", value: "completed_no_action" },
              { label: "blocked", value: "blocked" },
              { label: "unknown", value: "unknown" },
              { label: "failed", value: "failed" }
            ]
          },
          {
            type: "select",
            name: "trigger_mode",
            label: "触发方式",
            defaultValue: String(params.trigger_mode ?? ""),
            options: [
              { label: "全部", value: "" },
              { label: "automatic", value: "automatic" },
              { label: "manual_diagnostic", value: "manual_diagnostic" },
              { label: "manual_recovery", value: "manual_recovery" }
            ]
          },
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
      <SimpleTable
        rows={rows}
        columns={[
          { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/runs/${row.id}`}>{String(row.id)}</Link> },
          { key: "scheduled_for_utc", label: "周期时间", render: (row) => formatUtc(row.scheduled_for_utc) },
          { key: "cycle_kind", label: "周期" },
          { key: "trigger_mode", label: "触发方式" },
          { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
          { key: "final_outcome", label: "结果", render: (row) => <StatusBadge value={row.final_outcome} /> },
          { key: "current_step_code", label: "当前步骤" },
          { key: "needs_manual_attention", label: "需人工关注" },
          { key: "has_order_submission", label: "有订单提交" }
        ]}
      />
    </>
  );
}
