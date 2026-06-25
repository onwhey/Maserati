"use server";

import { revalidatePath } from "next/cache";

import { opsPost } from "@/lib/api/client";

type AIReviewCreateActionState = {
  submitted: boolean;
  ok: boolean;
  reason_code: string;
  message: string;
  data: Record<string, unknown> | null;
  ai_review_request_id: number | null;
};

function parseRunIds(rawValue: FormDataEntryValue | null): number[] | null {
  const raw = String(rawValue ?? "").trim();
  if (!raw) {
    return null;
  }

  const ids: number[] = [];
  for (const part of raw.split(/[\s,，]+/)) {
    if (!part) {
      continue;
    }
    const parsed = Number(part);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      return null;
    }
    ids.push(parsed);
  }

  return Array.from(new Set(ids)).sort((left, right) => left - right);
}

function buildRangeSelector(formData: FormData): Record<string, unknown> | null {
  const rangeType = String(formData.get("range_type") ?? "recent_runs").trim();
  if (rangeType === "recent_runs") {
    const limit = Number(formData.get("recent_limit") ?? 20);
    if (![20, 50, 100].includes(limit)) {
      return null;
    }
    return { type: "recent_runs", limit };
  }

  if (rangeType === "run_ids") {
    const ids = parseRunIds(formData.get("run_ids"));
    if (!ids || ids.length === 0) {
      return null;
    }
    return { type: "run_ids", ids };
  }

  if (rangeType === "utc_time_range") {
    const startUtc = String(formData.get("start_utc") ?? "").trim();
    const endUtc = String(formData.get("end_utc") ?? "").trim();
    if (!startUtc || !endUtc) {
      return null;
    }
    return { type: "utc_time_range", start_utc: startUtc, end_utc: endUtc };
  }

  return null;
}

function buildFilters(formData: FormData): Record<string, boolean> {
  return {
    only_problem_runs: formData.get("only_problem_runs") === "true",
    only_with_runtime_guard_issue: formData.get("only_with_runtime_guard_issue") === "true",
    only_with_orders: formData.get("only_with_orders") === "true"
  };
}

export async function createAIReviewRequestAction(
  _previousState: AIReviewCreateActionState,
  formData: FormData
): Promise<AIReviewCreateActionState> {
  const requestKey = String(formData.get("request_key") ?? "").trim();
  const reviewMode = String(formData.get("review_mode") ?? "").trim();
  const manualQuestion = String(formData.get("manual_question") ?? "").trim();
  const modelProfileCode = String(formData.get("model_profile_code") ?? "").trim();
  const traceId = String(formData.get("trace_id") ?? "").trim();
  const rangeSelector = buildRangeSelector(formData);

  if (!requestKey) {
    return {
      submitted: true,
      ok: false,
      reason_code: "ai_review_request_key_required",
      message: "AIReview 创建请求必须填写 request_key，用于防止重复创建同一复盘请求。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (requestKey.length > 191) {
    return {
      submitted: true,
      ok: false,
      reason_code: "ai_review_request_key_too_long",
      message: "request_key 不能超过 191 个字符。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (!reviewMode) {
    return {
      submitted: true,
      ok: false,
      reason_code: "ai_review_mode_required",
      message: "请选择复盘模式。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (!modelProfileCode) {
    return {
      submitted: true,
      ok: false,
      reason_code: "ai_review_model_profile_required",
      message: "请选择受控模型套餐编号；前端不得填写完整模型配置。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (modelProfileCode.length > 120) {
    return {
      submitted: true,
      ok: false,
      reason_code: "ai_review_model_profile_too_long",
      message: "模型套餐编号不能超过 120 个字符。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (reviewMode === "manual_question_review" && !manualQuestion) {
    return {
      submitted: true,
      ok: false,
      reason_code: "manual_question_required",
      message: "人工问题复盘必须填写明确问题。",
      data: null,
      ai_review_request_id: null
    };
  }
  if (!rangeSelector) {
    return {
      submitted: true,
      ok: false,
      reason_code: "invalid_review_range",
      message: "复盘范围不合法：请选择最近运行、显式编排 ID 或 UTC 时间范围。",
      data: null,
      ai_review_request_id: null
    };
  }

  const result = await opsPost<Record<string, unknown>>("/api/ops/ai-review/create/", {
    request_key: requestKey,
    review_mode: reviewMode,
    range_selector: rangeSelector,
    filters: buildFilters(formData),
    manual_question: manualQuestion,
    model_profile_code: modelProfileCode,
    trace_id: traceId || undefined
  });

  if (result.ok) {
    revalidatePath("/ai-review");
    const createdId = Number(result.data.ai_review_request_id ?? 0) || null;
    const requestStatus = String(result.data.request_status ?? "");
    return {
      submitted: true,
      ok: true,
      reason_code: result.reason_code,
      message: requestStatus
        ? `AIReview 请求已创建，当前状态：${requestStatus}。`
        : "AIReview 请求已创建。",
      data: result.data,
      ai_review_request_id: createdId
    };
  }

  return {
    submitted: true,
    ok: false,
    reason_code: result.reason_code,
    message: result.message_zh,
    data: null,
    ai_review_request_id: null
  };
}
