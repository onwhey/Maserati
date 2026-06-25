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

export default async function RunDetailPage({ params }: PageProps) {
  const { id } = await params;
  const result = await opsFetch<Record<string, unknown>>(`/api/ops/runs/${id}/`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const data = result.data;
  const steps = asRows(data.steps);
  const links = asRows(data.business_object_links);
  const alerts = asRows(data.related_alerts);
  const issues = asRows(data.related_runtime_guard_issues);

  return (
    <>
      <PageHeader title={`Run #${id}`} description="编排详情只展示 OrchestrationRun、StepRun、ObjectLink 和后端关联事实，不直接修改任何业务对象。" />
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>基本信息</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "run_key", value: data.run_key },
              { label: "pipeline_code", value: data.pipeline_code },
              { label: "scheduled_for_utc", value: formatUtc(data.scheduled_for_utc) },
              { label: "cycle_kind", value: data.cycle_kind },
              { label: "status", value: data.status },
              { label: "final_outcome", value: data.final_outcome },
              { label: "reason_code", value: data.reason_code },
              { label: "trace_id", value: data.trace_id },
              { label: "strategy_analysis_release_id", value: data.strategy_analysis_release_id }
            ]}
          />
        </CardContent>
      </Card>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-semibold">StepRun</h2>
        <SimpleTable
          rows={steps}
          columns={[
            { key: "step_code", label: "步骤" },
            { key: "module_code", label: "模块" },
            { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
            { key: "normalized_status", label: "统一状态" },
            { key: "flow_action", label: "流转动作" },
            { key: "reason_code", label: "原因" },
            { key: "primary_object_type", label: "主对象" },
            { key: "primary_object_id", label: "主对象 ID" }
          ]}
        />
      </section>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-semibold">业务对象索引</h2>
        <SimpleTable
          rows={links}
          columns={[
            { key: "step_code", label: "步骤" },
            { key: "object_role", label: "角色" },
            { key: "object_type", label: "对象类型" },
            { key: "object_id", label: "对象 ID" }
          ]}
        />
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>关联 AlertEvent</CardTitle></CardHeader>
          <CardContent>
            <SimpleTable
              rows={alerts}
              columns={[
                { key: "id", label: "ID" },
                { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
                { key: "event_type", label: "事件" },
                { key: "title_zh", label: "标题" }
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>关联 RuntimeGuardIssue</CardTitle></CardHeader>
          <CardContent>
            <SimpleTable
              rows={issues}
              columns={[
                { key: "id", label: "ID" },
                { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
                { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
                { key: "issue_type", label: "问题" }
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>原始只读响应</CardTitle></CardHeader>
        <CardContent><JsonBlock value={asRecord(data)} /></CardContent>
      </Card>
    </>
  );
}
