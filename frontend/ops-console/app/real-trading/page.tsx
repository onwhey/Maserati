import { ApiError } from "@/components/ops/api-error";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { StatusBadge } from "@/components/ops/status-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

export default async function RealTradingPage() {
  const result = await opsFetch<Record<string, unknown>>("/api/ops/real-trading/");
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const data = result.data;
  const runtimeConfig = asRecord(data.runtime_config);

  return (
    <>
      <PageHeader title="Real Trading" description="当前仅只读展示真实交易权限状态；本批次不提供开关修改入口。" />
      <Card className="mb-6">
        <CardHeader><CardTitle>权限状态</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: ".env 部署级硬权限", value: data.deployment_real_trading_permission },
              { label: "MySQL 运行开关", value: data.runtime_real_trading_permission },
              { label: "最终真实交易权限", value: data.effective_real_trading_permission ? "开启" : "关闭" },
              { label: "fail_closed", value: data.fail_closed },
              { label: "reason_code", value: data.reason_code },
              { label: "active_exchange", value: data.active_exchange },
              { label: "active_market_type", value: data.active_market_type },
              { label: "normalized_active_market_type", value: data.normalized_active_market_type },
              { label: "active_account_domain", value: data.active_account_domain },
              { label: "active_symbol", value: data.active_symbol }
            ]}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>运行开关审计摘要</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div>最终权限：<StatusBadge value={data.effective_real_trading_permission ? "allowed" : "blocked"} /></div>
          <KeyValueGrid
            items={[
              { label: "config_id", value: runtimeConfig.id },
              { label: "config_key", value: runtimeConfig.config_key },
              { label: "updated_by", value: runtimeConfig.updated_by },
              { label: "updated_reason", value: runtimeConfig.updated_reason },
              { label: "updated_at_utc", value: formatUtc(runtimeConfig.updated_at_utc) }
            ]}
          />
        </CardContent>
      </Card>
    </>
  );
}
