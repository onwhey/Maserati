import Link from "next/link";
import { Activity, AlertTriangle, Database, Lock, ShieldCheck } from "lucide-react";

import { ApiError } from "@/components/ops/api-error";
import { PageHeader } from "@/components/ops/page-header";
import { RecentRunStatusChart } from "@/components/ops/recent-run-status-chart";
import { SimpleTable } from "@/components/ops/simple-table";
import { StatCard } from "@/components/ops/stat-card";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

export default async function DashboardPage() {
  const result = await opsFetch<Record<string, unknown>>("/api/ops/dashboard/");
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const data = result.data;
  const recentRuns = asRows(data.recent_runs);
  const latestAlerts = asRows(data.latest_alerts);
  const realTrading = asRecord(data.real_trading);
  const tradeSync = asRecord(data.latest_trade_preparation_account_sync);
  const opsSync = asRecord(data.latest_ops_display_account_sync);

  return (
    <>
      <PageHeader title="Dashboard" description="快速查看系统运行事实；复盘数据由 Review Dataset 页面导出，本页不自行计算收益或复盘结论。" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Open RuntimeGuardIssue" value={String(data.open_runtime_guard_issue_count ?? 0)} icon={AlertTriangle} />
        <StatCard label="ActiveLock" value={String(data.active_lock_count ?? 0)} icon={Lock} />
        <StatCard
          label="真实交易最终权限"
          value={realTrading.effective_real_trading_permission ? "开启" : "关闭"}
          helper={`部署硬权限：${realTrading.deployment_real_trading_permission ? "允许" : "禁止"}`}
          icon={ShieldCheck}
        />
        <StatCard label="最近编排" value={recentRuns.length} helper="仅展示后端返回的最近记录" icon={Activity} />
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>最近编排状态分布</CardTitle>
          </CardHeader>
          <CardContent>
            <RecentRunStatusChart runs={recentRuns} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>账户事实边界</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <div className="rounded-lg border p-3">
              <div className="text-muted-foreground">trade_preparation</div>
              <div className="mt-1">状态：<StatusBadge value={tradeSync.status} /></div>
              <div className="mt-1">时间：{formatUtc(tradeSync.as_of_utc)}</div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-muted-foreground">ops_display</div>
              <div className="mt-1">状态：<StatusBadge value={opsSync.status} /></div>
              <div className="mt-1">时间：{formatUtc(opsSync.as_of_utc)}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6">
        <section>
          <h2 className="mb-3 text-lg font-semibold">最近 OrchestrationRun</h2>
          <SimpleTable
            rows={recentRuns}
            columns={[
              { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/runs/${row.id}`}>{String(row.id)}</Link> },
              { key: "scheduled_for_utc", label: "周期时间", render: (row) => formatUtc(row.scheduled_for_utc) },
              { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
              { key: "final_outcome", label: "最终结果", render: (row) => <StatusBadge value={row.final_outcome} /> },
              { key: "current_step_code", label: "当前步骤" },
              { key: "reason_code", label: "原因" }
            ]}
          />
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">最近 AlertEvent</h2>
          <SimpleTable
            rows={latestAlerts}
            columns={[
              { key: "id", label: "ID", render: (row) => <Link className="font-medium underline" href={`/alerts/${row.id}`}>{String(row.id)}</Link> },
              { key: "event_time_utc", label: "时间", render: (row) => formatUtc(row.event_time_utc) },
              { key: "severity", label: "级别", render: (row) => <StatusBadge value={row.severity} /> },
              { key: "source_module", label: "来源" },
              { key: "event_type", label: "事件" },
              { key: "title_zh", label: "标题" }
            ]}
          />
        </section>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Database className="h-4 w-4" />页面边界</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Dashboard 只展示后端 API 返回的事实；不直接访问数据库，不调用 Binance，不计算周期收益，不触发任何交易动作。
          </CardContent>
        </Card>
      </div>
    </>
  );
}
