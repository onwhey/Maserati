import Link from "next/link";

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

export default async function RuntimeGuardPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/runtime-guard/issues/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const rows = asRows(result.data.items);

  return (
    <>
      <PageHeader title="Runtime Guard" description="展示巡检发现的问题；本页不修复、不补跑、不释放锁。" />
      <FilterBar
        fields={[
          { type: "input", name: "status", label: "状态", placeholder: "open / resolved", defaultValue: String(params.status ?? "") },
          { type: "input", name: "severity", label: "级别", placeholder: "high / critical", defaultValue: String(params.severity ?? "") },
          { type: "input", name: "issue_type", label: "问题类型", defaultValue: String(params.issue_type ?? "") }
        ]}
      />
      <SimpleTable
        rows={rows}
        columns={[
          { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/runtime-guard/${row.id}`}>{String(row.id)}</Link> },
          { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
          { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
          { key: "issue_type", label: "问题类型" },
          { key: "related_object_type", label: "关联对象" },
          { key: "related_object_id", label: "对象 ID" },
          { key: "last_seen_at_utc", label: "最后发现", render: (row) => formatUtc(row.last_seen_at_utc) },
          { key: "needs_manual_attention", label: "需人工关注" }
        ]}
      />
    </>
  );
}
