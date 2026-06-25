import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";

export default function PerformancePage() {
  return (
    <>
      <PageHeader title="Performance" description="绩效复盘展示入口。" />
      <EmptyState
        title="PerformanceMetrics 后端接口尚未在本批次实现"
        description="本页不自行计算周期收益；后续必须读取 PerformanceMetrics 已落库结果，不能用订单 realized PnL 替代周期浮盈。"
      />
    </>
  );
}
