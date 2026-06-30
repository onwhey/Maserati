import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

export default async function StrategyReleasesPage() {
  const releasesResult = await opsFetch<Paginated<Record<string, unknown>>>("/api/ops/strategy-releases/");

  if (!releasesResult.ok) {
    return <ApiError reason={releasesResult.reason_code} message={releasesResult.message_zh} />;
  }

  const releases = asRows(releasesResult.data.items);

  return (
    <>
      <PageHeader
        title="策略发布"
        description="查看策略分析版本包，完成冻结、验证、批准和启用；本页不编辑算法代码，也不触发交易。"
      />

      <Card>
        <CardHeader>
          <CardTitle>版本包列表</CardTitle>
        </CardHeader>
        <CardContent>
          {releases.length ? (
            <SimpleTable
              rows={releases}
              columns={[
                {
                  key: "id",
                  label: "ID",
                  render: (row) => (
                    <Link className="font-medium underline" href={`/strategy-releases/${String(row.id)}`}>
                      {String(row.id)}
                    </Link>
                  )
                },
                { key: "release_code", label: "代码" },
                { key: "display_name", label: "名称" },
                { key: "approval_status", label: "状态", render: (row) => <StatusBadge value={row.approval_status} /> },
                { key: "is_active", label: "当前启用", render: (row) => <StatusBadge value={row.is_active} /> },
                { key: "validation_evidence_count", label: "证据数" },
                { key: "updated_at_utc", label: "更新时间", render: (row) => formatUtc(row.updated_at_utc) },
                {
                  key: "detail",
                  label: "操作",
                  render: (row) => (
                    <Link
                      className="inline-flex items-center rounded-md border px-3 py-1 text-sm text-foreground transition-colors hover:bg-muted"
                      href={`/strategy-releases/${String(row.id)}`}
                    >
                      查看详情
                    </Link>
                  )
                }
              ]}
            />
          ) : (
            <EmptyState title="暂无版本包" description="当前还没有 StrategyAnalysisRelease。" />
          )}
        </CardContent>
      </Card>
    </>
  );
}
