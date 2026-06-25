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

export default async function OrdersPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const result = await opsFetch<Paginated<Record<string, unknown>>>(`/api/ops/orders/${toSearchParams(params)}`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const rows = asRows(result.data.items);
  const pagination = asRecord(result.data.pagination);

  return (
    <>
      <PageHeader title="Orders" description="围绕 OrderSubmissionAttempt 查看订单链路事实；本页不重新提交订单，不补查，不补同步。" />
      <FilterBar
        fields={[
          { type: "input", name: "status", label: "提交状态", placeholder: "accepted / unknown / failed", defaultValue: String(params.status ?? "") },
          { type: "input", name: "symbol", label: "symbol", placeholder: "BTCUSDT", defaultValue: String(params.symbol ?? "") },
          { type: "input", name: "market_type", label: "market_type", defaultValue: String(params.market_type ?? "") },
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
          { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/orders/${row.id}`}>{String(row.id)}</Link> },
          { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) },
          { key: "status", label: "提交状态", render: (row) => <StatusBadge value={row.status} /> },
          { key: "exchange_status", label: "交易所状态", render: (row) => <StatusBadge value={row.exchange_status} /> },
          { key: "market_type", label: "市场" },
          { key: "account_domain", label: "账户域" },
          { key: "symbol", label: "symbol" },
          { key: "side", label: "方向" },
          { key: "quantity", label: "数量" },
          { key: "reason_code", label: "原因" }
        ]}
      />
    </>
  );
}
