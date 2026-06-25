import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { FilterBar } from "@/components/ops/filter-bar";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc, toSearchParams } from "@/lib/utils";

import { AIReviewCreateRequestForm } from "./create-request-form";

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AIReviewPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/ai-review/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const rows = asRows(result.data.items);
  const pagination = asRecord(result.data.pagination);

  return (
    <>
      <PageHeader
        title="AI Review"
        description="离线 AI 复盘请求、数据包、模型调用结果和人工建议查看入口；本页不参与实时交易。"
      />
      <AIReviewCreateRequestForm />
      <FilterBar
        fields={[
          { type: "input", name: "status", label: "状态", placeholder: "created / completed / failed", defaultValue: String(params.status ?? "") },
          { type: "input", name: "review_mode", label: "复盘模式", placeholder: "cycle_review", defaultValue: String(params.review_mode ?? "") },
          { type: "input", name: "request_key", label: "request_key", defaultValue: String(params.request_key ?? "") },
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
        <EmptyState title="暂无 AIReview 请求" description="可以通过受控 OpsConsole API 创建离线复盘请求；模型调用只能由 AIReview service 通过 DeepSeekGateway 完成。" />
      ) : (
        <SimpleTable
          rows={rows}
          columns={[
            { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/ai-review/${row.id}`}>{String(row.id)}</Link> },
            { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) },
            { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
            { key: "review_mode", label: "复盘模式" },
            { key: "request_key", label: "请求键" },
            { key: "requested_by", label: "请求人" },
            { key: "attempt_count", label: "调用次数" },
            { key: "reason_code", label: "原因" },
            { key: "model_profile_code", label: "模型套餐" }
          ]}
        />
      )}
    </>
  );
}
