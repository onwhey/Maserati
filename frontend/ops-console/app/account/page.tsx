import { ApiError } from "@/components/ops/api-error";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { PageHeader } from "@/components/ops/page-header";
import { SimpleTable } from "@/components/ops/simple-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRecord, asRows } from "@/lib/ops-data";
import { formatUtc } from "@/lib/utils";

export default async function AccountPage() {
  const result = await opsFetch<Record<string, unknown>>("/api/ops/account-overview/");
  if (!result.ok) {
    return <ApiError reason={result.reason_code} message={result.message_zh} />;
  }
  const data = result.data;
  const syncRun = asRecord(data.sync_run);
  const account = asRecord(data.account_snapshot);
  const balances = asRows(data.balances);
  const positions = asRows(data.positions);
  const symbolRules = asRows(data.symbol_rules);

  return (
    <>
      <PageHeader title="Account Overview" description="只展示 ops_display 账户快照；不触发账户刷新，不生成 trade_preparation，不参与交易主链路。" />
      <Card className="mb-6">
        <CardHeader><CardTitle>同步批次</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "reason_code", value: data.reason_code },
              { label: "sync_run_id", value: syncRun.id },
              { label: "sync_purpose", value: syncRun.sync_purpose },
              { label: "status", value: syncRun.status },
              { label: "market_type", value: syncRun.market_type },
              { label: "account_domain", value: syncRun.account_domain },
              { label: "as_of_utc", value: formatUtc(syncRun.as_of_utc) },
              { label: "trace_id", value: syncRun.trace_id }
            ]}
          />
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader><CardTitle>账户摘要</CardTitle></CardHeader>
        <CardContent>
          <KeyValueGrid
            items={[
              { label: "can_trade", value: account.can_trade },
              { label: "position_mode", value: account.position_mode },
              { label: "total_wallet_balance", value: account.total_wallet_balance },
              { label: "total_unrealized_profit", value: account.total_unrealized_profit },
              { label: "total_margin_balance", value: account.total_margin_balance },
              { label: "available_balance", value: account.available_balance },
              { label: "native_asset", value: account.native_asset },
              { label: "as_of_utc", value: formatUtc(account.as_of_utc) }
            ]}
          />
        </CardContent>
      </Card>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-semibold">余额</h2>
        <SimpleTable
          rows={balances}
          columns={[
            { key: "asset", label: "资产" },
            { key: "wallet_balance", label: "钱包余额" },
            { key: "available_balance", label: "可用余额" },
            { key: "cross_unrealized_pnl", label: "未实现收益" },
            { key: "update_time_utc", label: "更新时间", render: (row) => formatUtc(row.update_time_utc) }
          ]}
        />
      </section>

      <section className="mb-6">
        <h2 className="mb-3 text-lg font-semibold">持仓</h2>
        <SimpleTable
          rows={positions}
          columns={[
            { key: "symbol", label: "symbol" },
            { key: "normalized_position_side", label: "方向" },
            { key: "position_amount", label: "数量" },
            { key: "entry_price", label: "开仓价" },
            { key: "mark_price", label: "mark price" },
            { key: "unrealized_pnl", label: "未实现收益" },
            { key: "notional", label: "名义价值" },
            { key: "margin_mode", label: "保证金模式" }
          ]}
        />
      </section>

      <Card>
        <CardHeader><CardTitle>交易规则摘要</CardTitle></CardHeader>
        <CardContent>
          <JsonBlock value={symbolRules} />
        </CardContent>
      </Card>
    </>
  );
}
