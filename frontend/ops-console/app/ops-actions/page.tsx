import { PageHeader } from "@/components/ops/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const actions = [
  {
    title: "刷新 Account Overview",
    description: "请求 Binance 并写入 ops_display 账户展示快照；不生成 trade_preparation 快照。",
    endpoint: "POST /api/ops/account-overview/refresh/",
  },
  {
    title: "订单状态受控补查",
    description: "针对明确订单提交尝试执行一次恢复补查；不会重新提交订单，也不会释放 ActiveLock。",
    endpoint: "POST /api/ops/orders/{attempt_id}/status-recheck/",
  },
  {
    title: "成交受控补同步",
    description: "针对明确订单提交尝试和终态订单状态记录补齐成交事实；成交写入仍由 FillSync 完成。",
    endpoint: "POST /api/ops/orders/{attempt_id}/fill-sync/",
  },
  {
    title: "ActiveLock 人工收尾",
    description: "只调用 ActiveLockService；只有正式事实满足安全收尾条件时才会释放锁。",
    endpoint: "POST /api/ops/active-locks/{active_lock_id}/manual-closeout/",
  },
  {
    title: "RuntimeGuardIssue 状态标记",
    description: "只改变巡检问题的人工处理状态；不修改原业务对象。",
    endpoint: "POST /api/ops/runtime-guard/issues/{issue_id}/status/",
  },
  {
    title: "ReviewDataset 导出",
    description: "选择已落库编排事实，生成离线复盘数据集；不调用大模型，不保存复盘结论。",
    endpoint: "POST /api/ops/review-datasets/exports/create/",
  },
];

export default function OpsActionsPage() {
  return (
    <>
      <PageHeader title="Ops Actions" description="受控人工操作入口。所有写操作都需要权限、原因、二次确认和审计。" />
      <div className="grid gap-4 md:grid-cols-2">
        {actions.map((action) => (
          <Card key={action.endpoint}>
            <CardHeader>
              <CardTitle>{action.title}</CardTitle>
              <CardDescription>{action.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <code className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">{action.endpoint}</code>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
