import Link from "next/link";
import { Database } from "lucide-react";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

import { ReviewDatasetCreateExportForm } from "./create-export-form";

export default async function ReviewDatasetsPage() {
  const recordsResult = await opsFetch<Record<string, unknown>>("/api/ops/review-datasets/records/");
  const exportsResult = await opsFetch<Record<string, unknown>>("/api/ops/review-datasets/exports/");
  if (!recordsResult.ok) {
    return <ApiError reason={recordsResult.reason_code} message={recordsResult.message_zh} />;
  }
  if (!exportsResult.ok) {
    return <ApiError reason={exportsResult.reason_code} message={exportsResult.message_zh} />;
  }
  const records = asRows(recordsResult.data.items);
  const exports = asRows(exportsResult.data.items);

  return (
    <>
      <PageHeader
        title="Review Dataset"
        description="导出已落库事实，用于本地人工、脚本或 Codex skill 离线复盘；本页不保存复盘结论。"
      />
      <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
        <ReviewDatasetCreateExportForm />
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-4 w-4" />
              最近导出
            </CardTitle>
          </CardHeader>
          <CardContent>
            {exports.length ? (
              <SimpleTable
                rows={exports}
                columns={[
                  { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/review-datasets`}>{String(row.id)}</Link> },
                  { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
                  { key: "record_count", label: "记录数" },
                  { key: "export_format", label: "格式" },
                  { key: "storage_ref", label: "存储引用" },
                  { key: "created_at_utc", label: "创建时间", render: (row) => formatUtc(row.created_at_utc) }
                ]}
              />
            ) : (
              <EmptyState title="暂无导出" description="创建导出后，这里会显示 ReviewDatasetExport 记录。" />
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>最近 ReviewDatasetRecord</CardTitle>
        </CardHeader>
        <CardContent>
          {records.length ? (
            <SimpleTable
              rows={records}
              columns={[
                { key: "id", label: "ID" },
                { key: "subject_orchestration_run_id", label: "编排 ID" },
                { key: "period_start_utc", label: "周期开始", render: (row) => formatUtc(row.period_start_utc) },
                { key: "period_end_utc", label: "周期结束", render: (row) => formatUtc(row.period_end_utc) },
                { key: "build_status", label: "状态", render: (row) => <StatusBadge value={row.build_status} /> },
                { key: "missing_fact_count", label: "缺失事实数" },
                { key: "reason_code", label: "原因" }
              ]}
            />
          ) : (
            <EmptyState title="暂无数据集记录" description="ReviewDatasetRecord 只在预览确认并创建导出后生成。" />
          )}
        </CardContent>
      </Card>
    </>
  );
}
