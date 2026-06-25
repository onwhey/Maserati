import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

import { AIReviewRequestOperationPanel, AIReviewSuggestionStatusForm } from "../detail-operation-forms";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function AIReviewDetailPage({ params }: PageProps) {
  const { id } = await params;
  const requestId = Number(id);
  const result = await opsFetch<Record<string, unknown>>(`/api/ops/ai-review/${id}/`);
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }

  const request = asRecord(result.data.request);
  const activePackage = asRecord(result.data.active_package);
  const report = asRecord(result.data.report);
  const packages = asRows(result.data.packages);
  const attempts = asRows(result.data.attempts);
  const findings = asRows(result.data.findings);
  const suggestions = asRows(result.data.suggestions);
  const relatedAlerts = asRows(result.data.related_alerts);
  const auditRecords = asRows(result.data.audit_records);

  return (
    <>
      <PageHeader
        title={`AI Review #${id}`}
        description="离线 AI 复盘详情；这里展示已落库事实，不会触发交易，也不会直接调用 DeepSeekGateway。"
      />

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">请求概览</h2>
        <KeyValueGrid
          items={[
            { label: "状态", value: request.status },
            { label: "复盘模式", value: request.review_mode },
            { label: "请求键", value: request.request_key },
            { label: "模型套餐", value: request.model_profile_code },
            { label: "请求人", value: request.requested_by },
            { label: "原因", value: request.reason_code },
            { label: "创建时间", value: formatUtc(request.created_at_utc) },
            { label: "更新时间", value: formatUtc(request.updated_at_utc) },
            { label: "trace_id", value: request.trace_id }
          ]}
        />
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">冻结范围</h3>
            <JsonBlock value={{ range_selector: result.data.range_selector, filters: result.data.filters, frozen_run_ids: request.frozen_orchestration_run_ids }} />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">人工问题</h3>
            <JsonBlock value={result.data.manual_question || ""} />
          </div>
        </div>
      </section>

      <AIReviewRequestOperationPanel requestId={requestId} requestStatus={String(request.status ?? "")} />

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">当前数据包</h2>
        {Object.keys(activePackage).length === 0 ? (
          <EmptyState title="暂无数据包" description="请求尚未构建 AIReviewPackage，或构建已被阻断。" />
        ) : (
          <KeyValueGrid
            items={[
              { label: "package_id", value: activePackage.id },
              { label: "状态", value: activePackage.status },
              { label: "run 数", value: activePackage.run_count },
              { label: "订单数", value: activePackage.order_count },
              { label: "告警数", value: activePackage.alert_count },
              { label: "大小", value: activePackage.payload_size_bytes },
              { label: "是否脱敏", value: activePackage.sanitized },
              { label: "创建时间", value: formatUtc(activePackage.created_at_utc) }
            ]}
          />
        )}
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">模型调用尝试</h2>
        <SimpleTable
          rows={attempts}
          columns={[
            { key: "attempt_sequence", label: "序号" },
            { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
            { key: "gateway_status", label: "Gateway 状态", render: (row) => <StatusBadge value={row.gateway_status} /> },
            { key: "request_sent", label: "是否发送" },
            { key: "model_profile_code", label: "模型套餐" },
            { key: "total_token_count", label: "token" },
            { key: "error_code", label: "错误码" },
            { key: "finished_at_utc", label: "完成时间", render: (row) => formatUtc(row.finished_at_utc) }
          ]}
        />
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">复盘报告</h2>
        {Object.keys(report).length === 0 ? (
          <EmptyState title="暂无报告" description="只有模型调用成功且输出可解析时才会生成 AIReviewReport。" />
        ) : (
          <>
            <KeyValueGrid
              items={[
                { label: "标题", value: report.title },
                { label: "摘要", value: report.summary },
                { label: "置信度", value: report.confidence },
                { label: "prompt", value: `${String(report.prompt_name ?? "")} / ${String(report.prompt_version ?? "")}` },
                { label: "创建时间", value: formatUtc(report.created_at_utc) }
              ]}
            />
            <JsonBlock value={result.data.structured_report_json} />
          </>
        )}
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">发现</h2>
        <SimpleTable
          rows={findings}
          columns={[
            { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
            { key: "finding_type", label: "类型" },
            { key: "title", label: "标题" },
            { key: "needs_manual_attention", label: "需人工关注" },
            { key: "confidence", label: "置信度" }
          ]}
        />
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">人工建议</h2>
        <SimpleTable
          rows={suggestions}
          columns={[
            { key: "id", label: "ID" },
            { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
            { key: "suggestion_type", label: "类型" },
            { key: "priority", label: "优先级" },
            { key: "title", label: "标题" },
            { key: "target_area", label: "目标区域" },
            { key: "decision_note", label: "人工说明" },
            {
              key: "status_action",
              label: "人工状态操作",
              render: (row) => (
                <AIReviewSuggestionStatusForm
                  requestId={requestId}
                  suggestionId={Number(row.id ?? 0)}
                  currentStatus={String(row.status ?? "")}
                />
              )
            }
          ]}
        />
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">审计与事件</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">相关 AlertEvent</h3>
            <SimpleTable
              rows={relatedAlerts}
              columns={[
                { key: "id", label: "ID", render: (row) => <Link className="underline" href={`/alerts/${row.id}`}>{String(row.id)}</Link> },
                { key: "event_type", label: "事件" },
                { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
                { key: "event_time_utc", label: "时间", render: (row) => formatUtc(row.event_time_utc) }
              ]}
            />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">审计记录</h3>
            <SimpleTable
              rows={auditRecords}
              columns={[
                { key: "id", label: "ID" },
                { key: "operation_type", label: "操作" },
                { key: "operator_id", label: "操作者" },
                { key: "result", label: "结果", render: (row) => <StatusBadge value={row.result} /> },
                { key: "created_at_utc", label: "时间", render: (row) => formatUtc(row.created_at_utc) }
              ]}
            />
          </div>
        </div>
      </section>

      <section className="mt-8 space-y-3">
        <h2 className="text-lg font-semibold">历史数据包摘要</h2>
        <SimpleTable
          rows={packages}
          columns={[
            { key: "id", label: "ID" },
            { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
            { key: "run_count", label: "run 数" },
            { key: "payload_size_bytes", label: "字节数" },
            { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) }
          ]}
        />
      </section>
    </>
  );
}
