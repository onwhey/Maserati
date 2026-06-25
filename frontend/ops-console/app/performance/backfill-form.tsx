"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { runPerformanceBackfillAction } from "@/app/performance/actions";
import { JsonBlock } from "@/components/ops/json-block";
import { KeyValueGrid } from "@/components/ops/key-value";
import { StatusBadge } from "@/components/ops/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const initialPerformanceBackfillState = {
  submitted: false,
  ok: false,
  reason_code: "",
  message: "",
  data: null as Record<string, unknown> | null
};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "补算中..." : "一键补算缺失周期"}
    </Button>
  );
}

export function PerformanceBackfillForm({ preview }: { preview: Record<string, unknown> }) {
  const [state, formAction] = useActionState(runPerformanceBackfillAction, initialPerformanceBackfillState);

  return (
    <Card>
      <CardHeader>
        <CardTitle>后台一键补算</CardTitle>
        <CardDescription>
          只扫描缺失且可计算的已关闭 UTC 4 小时周期；写入 PerformanceMetrics 结果与审计，不进入自动交易主链路。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <KeyValueGrid
          items={[
            { label: "扫描周期数", value: preview.scanned_period_count },
            { label: "已有绩效记录", value: preview.existing_period_count },
            { label: "缺失周期数", value: preview.missing_period_count },
            { label: "可补算缺失周期", value: preview.calculable_missing_period_count }
          ]}
        />

        <form action={formAction} className="grid gap-3 rounded-xl border bg-slate-50 p-4">
          <label className="grid gap-1 text-sm">
            操作原因
            <Input name="reason" placeholder="例如：后台一键补齐缺失绩效周期" />
          </label>
          <label className="grid gap-1 text-sm">
            trace_id（可选）
            <Input name="trace_id" placeholder="留空则由后端生成默认追踪 ID" />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input name="confirm_write" value="true" type="checkbox" className="mt-1" />
            <span>
              我确认本次操作会写入 MySQL 中的绩效复盘结果、AuditRecord 和必要 AlertEvent；不会请求 Binance，不会提交订单，不会影响主交易编排。
            </span>
          </label>
          <div>
            <SubmitButton />
          </div>
        </form>

        {state.submitted ? (
          <div className="space-y-3 rounded-xl border bg-white p-4">
            <div className="flex items-center gap-2 text-sm">
              <span>本次结果：</span>
              <StatusBadge value={state.ok ? "succeeded" : "blocked"} />
              <span className="text-muted-foreground">{state.reason_code}</span>
            </div>
            <div className="text-sm">{state.message}</div>
            {state.data ? <JsonBlock value={state.data} /> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
