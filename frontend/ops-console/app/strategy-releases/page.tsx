import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { JsonBlock } from "@/components/ops/json-block";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

import { CreateDraftForm } from "./forms";

export default async function StrategyReleasesPage() {
  const releasesResult = await opsFetch<Paginated<Record<string, unknown>>>("/api/ops/strategy-releases/");
  const currentResult = await opsFetch<Record<string, unknown>>("/api/ops/strategy-releases/current/");
  const componentsResult = await opsFetch<Paginated<Record<string, unknown>>>("/api/ops/strategy-releases/components/");

  if (!releasesResult.ok) {
    return <ApiError reason={releasesResult.reason_code} message={releasesResult.message_zh} />;
  }
  if (!currentResult.ok) {
    return <ApiError reason={currentResult.reason_code} message={currentResult.message_zh} />;
  }
  if (!componentsResult.ok) {
    return <ApiError reason={componentsResult.reason_code} message={componentsResult.message_zh} />;
  }

  const releases = asRows(releasesResult.data.items);
  const current = asRecord(currentResult.data.release);
  const components = asRows(componentsResult.data.items);

  return (
    <>
      <PageHeader
        title="Strategy Release"
        description="组装、冻结、验证、批准和启用策略分析版本包；本页不编辑算法代码，也不触发交易。"
      />

      <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
        <CreateDraftForm />
        <Card>
          <CardHeader>
            <CardTitle>当前启用版本包</CardTitle>
          </CardHeader>
          <CardContent>
            {current.id ? (
              <JsonBlock value={current} />
            ) : (
              <EmptyState title="暂无当前版本包" description="没有 active 的 StrategyAnalysisRelease，新正式编排会在策略分析前阻断。" />
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
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
                { key: "updated_at_utc", label: "更新时间", render: (row) => formatUtc(row.updated_at_utc) }
              ]}
            />
          ) : (
            <EmptyState title="暂无版本包" description="先创建 draft，再从已登记组件中组装版本包。" />
          )}
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>可选组件概览</CardTitle>
        </CardHeader>
        <CardContent>
          {components.length ? (
            <SimpleTable
              rows={components.slice(0, 50)}
              columns={[
                { key: "component_type", label: "类型" },
                { key: "component_code", label: "代码" },
                { key: "version", label: "版本" },
                { key: "algorithm_name", label: "算法" },
                { key: "algorithm_version", label: "算法版本" },
                { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> }
              ]}
            />
          ) : (
            <EmptyState title="暂无可选组件" description="需要先通过 seed 或后台登记各层定义。" />
          )}
        </CardContent>
      </Card>
    </>
  );
}
