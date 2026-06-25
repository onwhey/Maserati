import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";

export default function AIReviewPage() {
  return (
    <>
      <PageHeader title="AI Review" description="离线 AI 复盘入口。" />
      <EmptyState
        title="AIReview 后端接口尚未在本批次实现"
        description="后续只能通过 AIReview service 和 DeepSeekGateway 处理离线复盘；页面不得提交完整 model profile、任意模型名或 provider 参数。"
      />
    </>
  );
}
