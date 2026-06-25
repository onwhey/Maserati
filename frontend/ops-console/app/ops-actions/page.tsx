import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";

export default function OpsActionsPage() {
  return (
    <>
      <PageHeader title="Ops Actions" description="受控人工操作入口。" />
      <EmptyState
        title="本批次不实现人工写操作"
        description="订单补查、成交补同步、ActiveLock 人工收尾、PerformanceMetrics 补算和 AIReview 创建必须等对应后端 service 与审计能力落地后再开放。"
      />
    </>
  );
}
