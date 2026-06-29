import { ApiError } from "@/components/ops/api-error";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, nestedRecord, nestedRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function OrderDetailPage({ params }: PageProps) {
  const { id } = await params;
  const result = await opsFetch<Record<string, unknown>>(`/api/ops/orders/${id}/`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const data = result.data;
  const attempt = nestedRecord(data, "order_submission_attempt");
  const statusRecords = nestedRows(data, "order_status_sync_records");
  const fillResults = nestedRows(data, "fill_sync_results");
  const tradeFills = nestedRows(data, "trade_fills");
  const relatedRuns = nestedRows(data, "related_orchestration_runs");
  const alerts = nestedRows(data, "related_alerts");
  const issues = nestedRows(data, "related_runtime_guard_issues");

  return (
    <>
      <PageHeader title={`OrderSubmissionAttempt #${id}`} description="订单详情只展示已有订单、状态与成交事实；unknown 不解释为成功或失败。" />
      <Card className="mb-6">
        <CardHeader><CardTitle>提交尝试</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "status", value: attempt.status },
              { label: "reason_code", value: attempt.reason_code },
              { label: "exchange_status", value: attempt.exchange_status },
              { label: "market_type", value: attempt.market_type },
              { label: "account_domain", value: attempt.account_domain },
              { label: "symbol", value: attempt.symbol },
              { label: "side", value: attempt.side },
              { label: "position_side", value: attempt.position_side },
              { label: "order_type", value: attempt.order_type },
              { label: "quantity", value: attempt.quantity },
              { label: "client_order_id", value: attempt.client_order_id },
              { label: "exchange_order_id", value: attempt.exchange_order_id },
              { label: "submitted_at_utc", value: formatUtc(attempt.submitted_at_utc) },
              { label: "finished_at_utc", value: formatUtc(attempt.finished_at_utc) },
              { label: "trace_id", value: attempt.trace_id }
            ]}
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        {[
          ["order_plan", "OrderPlan"],
          ["candidate_order_intent", "CandidateOrderIntent"],
          ["risk_check_result", "RiskCheckResult"],
          ["approved_order_intent", "ApprovedOrderIntent"],
          ["prepared_order_intent", "PreparedOrderIntent"],
          ["active_lock", "ActiveLock"],
          ["order_fill_summary", "OrderFillSummary"]
        ].map(([key, title]) => (
          <Card key={key}>
            <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
            <CardContent><JsonBlock value={asRecord(data[key])} /></CardContent>
          </Card>
        ))}
      </div>

      <section className="mt-6">
        <h2 className="mb-3 text-lg font-semibold">OrderStatusSyncRecord</h2>
        <SimpleTable
          rows={statusRecords}
          columns={[
            { key: "id", label: "ID" },
            { key: "poll_sequence", label: "轮次" },
            { key: "query_outcome", label: "查询结果", render: (row) => <StatusBadge value={row.query_outcome} /> },
            { key: "exchange_status", label: "交易所状态" },
            { key: "is_terminal_status", label: "终态" },
            { key: "submission_resolution_status", label: "提交解析" },
            { key: "created_at_utc", label: "时间", render: (row) => formatUtc(row.created_at_utc) }
          ]}
        />
      </section>

      <section className="mt-6">
        <h2 className="mb-3 text-lg font-semibold">FillSync / TradeFill</h2>
        <div className="grid gap-4">
          <SimpleTable
            rows={fillResults}
            columns={[
              { key: "id", label: "ID" },
              { key: "sync_sequence", label: "轮次" },
              { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
              { key: "returned_fill_count", label: "返回成交" },
              { key: "inserted_fill_count", label: "新增成交" },
              { key: "created_at_utc", label: "时间", render: (row) => formatUtc(row.created_at_utc) }
            ]}
          />
          <SimpleTable
            rows={tradeFills}
            columns={[
              { key: "id", label: "ID" },
              { key: "exchange_trade_id", label: "交易所成交 ID" },
              { key: "price", label: "价格" },
              { key: "quantity", label: "数量" },
              { key: "commission", label: "手续费" },
              { key: "realized_pnl", label: "订单级已实现收益" },
              { key: "trade_time_utc", label: "成交时间", render: (row) => formatUtc(row.trade_time_utc) }
            ]}
          />
        </div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card><CardHeader><CardTitle>关联编排</CardTitle></CardHeader><CardContent><JsonBlock value={relatedRuns} /></CardContent></Card>
        <Card><CardHeader><CardTitle>关联告警</CardTitle></CardHeader><CardContent><JsonBlock value={alerts} /></CardContent></Card>
        <Card><CardHeader><CardTitle>关联巡检问题</CardTitle></CardHeader><CardContent><JsonBlock value={issues} /></CardContent></Card>
      </div>
    </>
  );
}
