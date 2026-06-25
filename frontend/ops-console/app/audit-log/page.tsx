import { ApiError } from "@/components/ops/api-error";
import { FilterBar } from "@/components/ops/filter-bar";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRows } from "@/lib/ops-data";
import { formatUtc, toSearchParams } from "@/lib/utils";

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AuditLogPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/audit-log/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const rows = asRows(result.data.items);

  return (
    <>
      <PageHeader title="Audit Log" description="展示后端已脱敏审计记录；本页不删除、不修改审计事实。" />
      <FilterBar
        fields={[
          { type: "input", name: "operator_id", label: "操作人", defaultValue: String(params.operator_id ?? "") },
          { type: "input", name: "operation_type", label: "操作类型", defaultValue: String(params.operation_type ?? "") },
          { type: "input", name: "target_object_type", label: "目标对象类型", defaultValue: String(params.target_object_type ?? "") },
          { type: "input", name: "trace_id", label: "trace_id", defaultValue: String(params.trace_id ?? "") }
        ]}
      />
      <SimpleTable
        rows={rows}
        columns={[
          { key: "id", label: "ID" },
          { key: "created_at_utc", label: "时间", render: (row) => formatUtc(row.created_at_utc) },
          { key: "operator_id", label: "操作人" },
          { key: "operation_type", label: "操作类型" },
          { key: "target_object_type", label: "对象类型" },
          { key: "target_object_id", label: "对象 ID" },
          { key: "result", label: "结果", render: (row) => <StatusBadge value={row.result} /> },
          { key: "reason", label: "原因" },
          { key: "trace_id", label: "trace_id" }
        ]}
      />
    </>
  );
}
