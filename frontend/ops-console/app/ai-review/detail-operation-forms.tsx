"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import {
  buildAIReviewPackageAction,
  runAIReviewAction,
  updateAIReviewSuggestionStatusAction
} from "@/app/ai-review/detail-actions";
import { JsonBlock } from "@/components/ops/json-block";
import { StatusBadge } from "@/components/ops/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const initialAIReviewOperationState = {
  submitted: false,
  ok: false,
  reason_code: "",
  message: "",
  data: null as Record<string, unknown> | null
};

function SubmitButton({ children, variant = "default" }: { children: string; variant?: "default" | "secondary" | "outline" }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" variant={variant} disabled={pending}>
      {pending ? "提交中..." : children}
    </Button>
  );
}

function OperationResult({ state }: { state: typeof initialAIReviewOperationState }) {
  if (!state.submitted) {
    return null;
  }
  return (
    <div className="space-y-2 rounded-lg border bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span>结果：</span>
        <StatusBadge value={state.ok ? "succeeded" : "blocked"} />
        <span className="text-muted-foreground">{state.reason_code}</span>
      </div>
      <div>{state.message}</div>
      {state.data ? <JsonBlock value={state.data} /> : null}
    </div>
  );
}

export function AIReviewRequestOperationPanel({
  requestId,
  requestStatus
}: {
  requestId: number;
  requestStatus: string;
}) {
  const [buildState, buildFormAction] = useActionState(buildAIReviewPackageAction, initialAIReviewOperationState);
  const [runState, runFormAction] = useActionState(runAIReviewAction, initialAIReviewOperationState);

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>人工复盘操作</CardTitle>
        <CardDescription>
          这些按钮只由后台人工点击触发；不会加入自动交易主链路，也不会定时自动调用 DeepSeek。当前请求状态：{requestStatus || "—"}。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <form action={buildFormAction} className="space-y-3 rounded-xl border bg-slate-50 p-4">
          <input name="request_id" type="hidden" value={requestId} />
          <div>
            <h3 className="text-sm font-semibold">构建复盘数据包</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              后端从已落库事实读取、脱敏并生成 AIReviewPackage；前端不上传业务事实。
            </p>
          </div>
          <label className="grid gap-1 text-sm">
            trace_id（可选）
            <Input name="trace_id" placeholder="留空则由后端沿用默认追踪 ID" />
          </label>
          <SubmitButton variant="secondary">构建数据包</SubmitButton>
          <OperationResult state={buildState} />
        </form>

        <form action={runFormAction} className="space-y-3 rounded-xl border bg-slate-50 p-4">
          <input name="request_id" type="hidden" value={requestId} />
          <div>
            <h3 className="text-sm font-semibold">执行离线复盘</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              后端通过 AIReview service 调用 DeepSeekGateway；前端不直接调用 DeepSeek，也不执行任何 AI 建议。
            </p>
          </div>
          <label className="grid gap-1 text-sm">
            trace_id（可选）
            <Input name="trace_id" placeholder="留空则由后端沿用默认追踪 ID" />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input name="confirm_model_call" value="true" type="checkbox" className="mt-1" />
            <span>我确认本次操作可能触发一次 DeepSeek 离线复盘调用；结果只作为人工参考，不进入交易决策。</span>
          </label>
          <SubmitButton>执行离线复盘</SubmitButton>
          <OperationResult state={runState} />
        </form>
      </CardContent>
    </Card>
  );
}

export function AIReviewSuggestionStatusForm({
  requestId,
  suggestionId,
  currentStatus
}: {
  requestId: number;
  suggestionId: number;
  currentStatus: string;
}) {
  const [state, formAction] = useActionState(updateAIReviewSuggestionStatusAction, initialAIReviewOperationState);

  return (
    <form action={formAction} className="min-w-72 space-y-2">
      <input name="request_id" type="hidden" value={requestId} />
      <input name="suggestion_id" type="hidden" value={suggestionId} />
      <Select name="new_status" defaultValue={currentStatus || "pending_review"}>
        <option value="pending_review">pending_review</option>
        <option value="accepted">accepted</option>
        <option value="rejected">rejected</option>
        <option value="converted_to_task">converted_to_task</option>
        <option value="implemented">implemented</option>
        <option value="ignored">ignored</option>
      </Select>
      <Input name="decision_note" placeholder="人工说明；非 pending_review 必填" />
      <Input name="trace_id" placeholder="trace_id（可选）" />
      <SubmitButton variant="outline">更新建议状态</SubmitButton>
      <OperationResult state={state} />
    </form>
  );
}
