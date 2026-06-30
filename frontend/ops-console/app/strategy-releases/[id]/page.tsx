import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { JsonBlock } from "@/components/ops/json-block";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { displayValue, formatUtc } from "@/lib/utils";

import { CopyDraftForm, DraftEditForms, ReleaseStateActionForms, RemoveItemForm } from "../forms";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function StrategyReleaseDetailPage({ params }: PageProps) {
  const { id } = await params;
  const detailResult = await opsFetch<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/`);
  if (!detailResult.ok) {
    return <ApiError reason={detailResult.reason_code} message={detailResult.message_zh} />;
  }

  const release = asRecord(detailResult.data.release);
  const items = asRows(detailResult.data.items);
  const evidence = asRows(detailResult.data.validation_evidence);
  const approvals = asRows(detailResult.data.approvals);
  const activations = asRows(detailResult.data.activations);
  const releaseId = Number(release.id ?? 0);
  const isDraft = release.approval_status === "draft";

  return (
    <>
      <div className="mb-4">
        <Link className="text-sm text-muted-foreground underline" href="/strategy-releases">
          返回 Strategy Release
        </Link>
      </div>
      <PageHeader
        title={`Strategy Release #${displayValue(release.id)}`}
        description="查看版本包组件、验证证据和状态流转；所有写操作都会调用后端受控 service。"
      />

      <Card>
        <CardHeader>
          <CardTitle>版本包摘要</CardTitle>
        </CardHeader>
        <CardContent>
          <SimpleTable
            rows={[release]}
            columns={[
              { key: "release_code", label: "代码" },
              { key: "display_name", label: "名称" },
              { key: "approval_status", label: "状态", render: (row) => <StatusBadge value={row.approval_status} /> },
              { key: "is_active", label: "当前启用", render: (row) => <StatusBadge value={row.is_active} /> },
              { key: "release_hash", label: "指纹" },
              { key: "updated_at_utc", label: "更新时间", render: (row) => formatUtc(row.updated_at_utc) }
            ]}
          />
        </CardContent>
      </Card>

      {isDraft ? (
        <div className="mt-6">
          <DraftEditForms release={release} />
        </div>
      ) : null}

      <div className="mt-6">
        <CopyDraftForm release={release} />
      </div>

      <div className="mt-6">
        <ReleaseStateActionForms release={release} />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>ReleaseItem 清单</CardTitle>
        </CardHeader>
        <CardContent>
          {items.length ? (
            <SimpleTable
              rows={items}
              columns={[
                { key: "component_type", label: "类型" },
                { key: "component_code", label: "代码" },
                { key: "component_object_id", label: "对象 ID" },
                { key: "algorithm_name", label: "算法" },
                { key: "algorithm_version", label: "算法版本" },
                { key: "definition_hash", label: "定义指纹" },
                {
                  key: "actions",
                  label: "操作",
                  render: (row) =>
                    isDraft ? <RemoveItemForm releaseId={releaseId} itemId={Number(row.id ?? 0)} /> : <span className="text-muted-foreground">已冻结</span>
                }
              ]}
            />
          ) : (
            <EmptyState title="暂无组件" description="请从策略组件页配置后生成新的草稿。" />
          )}
        </CardContent>
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>验证证据</CardTitle>
          </CardHeader>
          <CardContent>{evidence.length ? <JsonBlock value={evidence} /> : <EmptyState title="暂无验证证据" description="冻结后登记验证证据。" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>批准记录</CardTitle>
          </CardHeader>
          <CardContent>{approvals.length ? <JsonBlock value={approvals} /> : <EmptyState title="暂无批准记录" description="批准、拒绝、失效会记录在这里。" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>启用记录</CardTitle>
          </CardHeader>
          <CardContent>{activations.length ? <JsonBlock value={activations} /> : <EmptyState title="暂无启用记录" description="启用或回滚后会记录在这里。" />}</CardContent>
        </Card>
      </div>
    </>
  );
}
