"use client";

import Link from "next/link";
import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { createAIReviewRequestAction } from "@/app/ai-review/actions";
import { JsonBlock } from "@/components/ops/json-block";
import { StatusBadge } from "@/components/ops/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const REVIEW_MODES = [
  { value: "cycle_review", label: "周期复盘" },
  { value: "anomaly_review", label: "异常复盘" },
  { value: "order_lifecycle_review", label: "订单生命周期复盘" },
  { value: "performance_attribution_review", label: "绩效归因复盘" },
  { value: "manual_question_review", label: "人工问题复盘" }
];

const initialAIReviewCreateState = {
  submitted: false,
  ok: false,
  reason_code: "",
  message: "",
  data: null as Record<string, unknown> | null,
  ai_review_request_id: null as number | null
};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending}>
      {pending ? "创建中..." : "创建离线复盘请求"}
    </Button>
  );
}

export function AIReviewCreateRequestForm() {
  const [state, formAction] = useActionState(createAIReviewRequestAction, initialAIReviewCreateState);
  const [rangeType, setRangeType] = useState("recent_runs");

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>创建 AIReview 离线复盘请求</CardTitle>
        <CardDescription>
          本表单只选择复盘范围、复盘模式和受控模型套餐；不会上传特征、原子信号、订单、成交等业务事实，数据包由后端 AIReview service 从已落库事实中构建和脱敏。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form action={formAction} className="grid gap-4 rounded-xl border bg-slate-50 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm">
              request_key
              <Input
                name="request_key"
                required
                maxLength={191}
                placeholder="例如：ai-review-2026-06-25-cycle-001"
              />
              <span className="text-xs text-muted-foreground">相同 request_key 重复提交会返回同一个复盘请求。</span>
            </label>
            <label className="grid gap-1 text-sm">
              模型套餐编号
              <Input name="model_profile_code" required maxLength={120} defaultValue="default_review" />
              <span className="text-xs text-muted-foreground">这里只能填写套餐编号，不能填写模型名、API key 或供应商配置。</span>
            </label>
            <label className="grid gap-1 text-sm">
              复盘模式
              <Select name="review_mode" required defaultValue="cycle_review">
                {REVIEW_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="grid gap-1 text-sm">
              trace_id（可选）
              <Input name="trace_id" placeholder="留空则由后端使用默认追踪 ID" />
            </label>
          </div>

          <div className="grid gap-3 rounded-lg border bg-white p-3">
            <label className="grid gap-1 text-sm">
              复盘范围
              <Select name="range_type" value={rangeType} onChange={(event) => setRangeType(event.target.value)}>
                <option value="recent_runs">最近自动编排运行</option>
                <option value="run_ids">指定编排运行 ID</option>
                <option value="utc_time_range">UTC 时间范围</option>
              </Select>
            </label>

            {rangeType === "recent_runs" ? (
              <label className="grid gap-1 text-sm">
                最近运行数量
                <Select name="recent_limit" defaultValue="20">
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                </Select>
              </label>
            ) : null}

            {rangeType === "run_ids" ? (
              <label className="grid gap-1 text-sm">
                编排运行 ID
                <Input name="run_ids" placeholder="例如：101,102,103" />
                <span className="text-xs text-muted-foreground">只提交 ID，后端会按这些 ID 读取已落库事实。</span>
              </label>
            ) : null}

            {rangeType === "utc_time_range" ? (
              <div className="grid gap-3 md:grid-cols-2">
                <label className="grid gap-1 text-sm">
                  开始 UTC
                  <Input name="start_utc" placeholder="2026-06-25T00:00:00Z" />
                </label>
                <label className="grid gap-1 text-sm">
                  结束 UTC
                  <Input name="end_utc" placeholder="2026-06-26T00:00:00Z" />
                </label>
              </div>
            ) : null}

            <div className="grid gap-2 text-sm md:grid-cols-3">
              <label className="flex items-start gap-2">
                <input name="only_problem_runs" value="true" type="checkbox" className="mt-1" />
                <span>只复盘异常 / 阻断 / 失败运行</span>
              </label>
              <label className="flex items-start gap-2">
                <input name="only_with_runtime_guard_issue" value="true" type="checkbox" className="mt-1" />
                <span>只复盘存在 RuntimeGuard 问题的运行</span>
              </label>
              <label className="flex items-start gap-2">
                <input name="only_with_orders" value="true" type="checkbox" className="mt-1" />
                <span>只复盘产生订单链路对象的运行</span>
              </label>
            </div>
          </div>

          <label className="grid gap-1 text-sm">
            人工问题（仅人工问题复盘必填）
            <textarea
              name="manual_question"
              maxLength={4000}
              className="min-h-24 w-full rounded-md border bg-white px-3 py-2 text-sm shadow-sm outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-slate-300"
              placeholder="例如：请解释最近 20 次编排中被风控阻断最多的原因。"
            />
          </label>

          <div>
            <SubmitButton />
          </div>
        </form>

        {state.submitted ? (
          <div className="space-y-3 rounded-xl border bg-white p-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>创建结果：</span>
              <StatusBadge value={state.ok ? "succeeded" : "blocked"} />
              <span className="text-muted-foreground">{state.reason_code}</span>
              {state.ai_review_request_id ? (
                <Link className="underline" href={`/ai-review/${state.ai_review_request_id}`}>
                  查看请求 #{state.ai_review_request_id}
                </Link>
              ) : null}
            </div>
            <div className="text-sm">{state.message}</div>
            {state.data ? <JsonBlock value={state.data} /> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
