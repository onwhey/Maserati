import { ApiError } from "@/components/ops/api-error";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function RuntimeGuardIssueDetailPage({ params }: PageProps) {
  const { id } = await params;
  const result = await opsFetch<Record<string, unknown>>(`/api/ops/runtime-guard/issues/${id}/`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const issue = asRecord(result.data.issue);

  return (
    <>
      <PageHeader title={`RuntimeGuardIssue #${id}`} description="区分巡检发现的问题和原业务对象状态；本页只展示，不处理。" />
      <Card className="mb-6">
        <CardHeader><CardTitle>问题摘要</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "issue_key", value: issue.issue_key },
              { label: "issue_type", value: issue.issue_type },
              { label: "severity", value: issue.severity },
              { label: "status", value: issue.status },
              { label: "needs_manual_attention", value: issue.needs_manual_attention },
              { label: "related_object_type", value: issue.related_object_type },
              { label: "related_object_id", value: issue.related_object_id },
              { label: "first_seen_at_utc", value: formatUtc(issue.first_seen_at_utc) },
              { label: "last_seen_at_utc", value: formatUtc(issue.last_seen_at_utc) }
            ]}
          />
        </CardContent>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>证据</CardTitle></CardHeader><CardContent><JsonBlock value={result.data.evidence} /></CardContent></Card>
        <Card><CardHeader><CardTitle>关联 AlertEvent</CardTitle></CardHeader><CardContent><JsonBlock value={result.data.related_alert} /></CardContent></Card>
      </div>
    </>
  );
}
