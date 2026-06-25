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

export default async function AlertsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/alerts/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const rows = asRows(result.data.items);

  return (
    <>
      <PageHeader title="Alerts" description="展示 AlertEvent 和通知审计入口；AlertEvent 只用于展示、通知和审计，不触发交易。" />
      <FilterBar
        fields={[
          { type: "input", name: "severity", label: "级别", defaultValue: String(params.severity ?? "") },
          { type: "input", name: "source_module", label: "来源模块", defaultValue: String(params.source_module ?? "") },
          { type: "input", name: "event_type", label: "事件类型", defaultValue: String(params.event_type ?? "") },
          { type: "input", name: "trace_id", label: "trace_id", defaultValue: String(params.trace_id ?? "") }
        ]}
      />
      <SimpleTable
        rows={rows}
        columns={[
          { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/alerts/${row.id}`}>{String(row.id)}</Link> },
          { key: "event_time_utc", label: "时间", render: (row) => formatUtc(row.event_time_utc) },
          { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
          { key: "source_module", label: "来源模块" },
          { key: "event_type", label: "事件类型" },
          { key: "event_category", label: "分类" },
          { key: "title_zh", label: "标题" },
          { key: "delivery_enabled", label: "外部投递" }
        ]}
      />
    </>
  );
}
