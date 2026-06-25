import { ApiError } from "@/components/ops/api-error";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function AlertDetailPage({ params }: PageProps) {
  const { id } = await params;
  const result = await opsFetch<Record<string, unknown>>(`/api/ops/alerts/${id}/`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const alert = asRecord(result.data.alert);
  const attempts = asRows(result.data.delivery_attempts);
  const suppressions = asRows(result.data.suppressions);

  return (
    <>
      <PageHeader title={`AlertEvent #${id}`} description="告警详情展示业务事件、投递尝试和抑制记录；通知成功或失败都不触发业务动作。" />
      <Card className="mb-6">
        <CardHeader><CardTitle>事件摘要</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "event_key", value: alert.event_key },
              { label: "source_module", value: alert.source_module },
              { label: "event_type", value: alert.event_type },
              { label: "event_category", value: alert.event_category },
              { label: "severity", value: alert.severity },
              { label: "title_zh", value: alert.title_zh },
              { label: "business_status", value: alert.business_status },
              { label: "reason_code", value: alert.reason_code },
              { label: "related_object_type", value: alert.related_object_type },
              { label: "related_object_id", value: alert.related_object_id },
              { label: "trace_id", value: alert.trace_id },
              { label: "event_time_utc", value: formatUtc(alert.event_time_utc) },
              { label: "delivery_enabled", value: alert.delivery_enabled }
            ]}
          />
        </CardContent>
      </Card>

      <div className="mb-6 grid gap-6 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>payload_summary</CardTitle></CardHeader><CardContent><JsonBlock value={result.data.payload_summary} /></CardContent></Card>
        <Card><CardHeader><CardTitle>evidence_refs</CardTitle></CardHeader><CardContent><JsonBlock value={result.data.evidence_refs} /></CardContent></Card>
      </div>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-semibold">NotificationDeliveryAttempt</h2>
        <SimpleTable
          rows={attempts}
          columns={[
            { key: "id", label: "ID" },
            { key: "channel", label: "通道" },
            { key: "delivery_status", label: "状态", render: (row) => <StatusBadge value={row.delivery_status} /> },
            { key: "attempt_sequence", label: "尝试次数" },
            { key: "request_sent", label: "已发送请求" },
            { key: "http_status", label: "HTTP" },
            { key: "retryable", label: "可重试" },
            { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) }
          ]}
        />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">NotificationSuppression</h2>
        <SimpleTable
          rows={suppressions}
          columns={[
            { key: "id", label: "ID" },
            { key: "suppression_type", label: "抑制类型" },
            { key: "reason_code", label: "原因" },
            { key: "dedupe_key", label: "去重键" },
            { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) }
          ]}
        />
      </section>
    </>
  );
}
