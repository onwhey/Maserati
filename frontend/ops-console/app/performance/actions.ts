"use server";

import { revalidatePath } from "next/cache";

import { opsPost } from "@/lib/api/client";

type PerformanceBackfillActionState = {
  submitted: boolean;
  ok: boolean;
  reason_code: string;
  message: string;
  data: Record<string, unknown> | null;
};

export async function runPerformanceBackfillAction(
  _previousState: PerformanceBackfillActionState,
  formData: FormData
): Promise<PerformanceBackfillActionState> {
  const confirmWrite = formData.get("confirm_write") === "true";
  const reason = String(formData.get("reason") ?? "").trim();
  const traceId = String(formData.get("trace_id") ?? "").trim();

  if (!confirmWrite) {
    return {
      submitted: true,
      ok: false,
      reason_code: "performance_backfill_confirm_write_required",
      message: "绩效补算会写入复盘结果，必须先确认本次操作。",
      data: null
    };
  }
  if (!reason) {
    return {
      submitted: true,
      ok: false,
      reason_code: "performance_backfill_reason_required",
      message: "绩效补算需要填写操作原因。",
      data: null
    };
  }

  const result = await opsPost<Record<string, unknown>>("/api/ops/performance/backfill/", {
    confirm_write: true,
    reason,
    trace_id: traceId || undefined
  });

  if (result.ok) {
    revalidatePath("/performance");
    return {
      submitted: true,
      ok: true,
      reason_code: result.reason_code,
      message: String(result.data.message ?? "绩效一键补算已完成。"),
      data: result.data
    };
  }

  return {
    submitted: true,
    ok: false,
    reason_code: result.reason_code,
    message: result.message_zh,
    data: null
  };
}
