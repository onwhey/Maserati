"use server";

import { revalidatePath } from "next/cache";

import { opsPost } from "@/lib/api/client";
import type { OpsApiResponse } from "@/lib/api/types";

type AIReviewOperationActionState = {
  submitted: boolean;
  ok: boolean;
  reason_code: string;
  message: string;
  data: Record<string, unknown> | null;
};

function positiveIntegerFromForm(formData: FormData, fieldName: string): number | null {
  const parsed = Number(formData.get(fieldName) ?? 0);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function blockedState(reason_code: string, message: string): AIReviewOperationActionState {
  return {
    submitted: true,
    ok: false,
    reason_code,
    message,
    data: null
  };
}

function stateFromResult(
  result: OpsApiResponse<Record<string, unknown>>,
  successMessage: string
): AIReviewOperationActionState {
  if (result.ok) {
    return {
      submitted: true,
      ok: true,
      reason_code: result.reason_code,
      message: String(result.data.message ?? successMessage),
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

export async function buildAIReviewPackageAction(
  _previousState: AIReviewOperationActionState,
  formData: FormData
): Promise<AIReviewOperationActionState> {
  const requestId = positiveIntegerFromForm(formData, "request_id");
  if (!requestId) {
    return blockedState("invalid_ai_review_request_id", "AIReviewRequest ID 不合法。");
  }

  const traceId = String(formData.get("trace_id") ?? "").trim();
  const result = await opsPost<Record<string, unknown>>(`/api/ops/ai-review/${requestId}/build-package/`, {
    trace_id: traceId || undefined
  });
  revalidatePath(`/ai-review/${requestId}`);
  return stateFromResult(result, "AIReviewPackage 构建请求已提交。");
}

export async function runAIReviewAction(
  _previousState: AIReviewOperationActionState,
  formData: FormData
): Promise<AIReviewOperationActionState> {
  const requestId = positiveIntegerFromForm(formData, "request_id");
  if (!requestId) {
    return blockedState("invalid_ai_review_request_id", "AIReviewRequest ID 不合法。");
  }
  if (formData.get("confirm_model_call") !== "true") {
    return blockedState("ai_review_model_call_confirmation_required", "执行离线复盘可能调用 DeepSeek，必须先明确确认。");
  }

  const traceId = String(formData.get("trace_id") ?? "").trim();
  const result = await opsPost<Record<string, unknown>>(`/api/ops/ai-review/${requestId}/run/`, {
    trace_id: traceId || undefined
  });
  revalidatePath(`/ai-review/${requestId}`);
  return stateFromResult(result, "AIReview 离线复盘执行请求已提交。");
}

export async function updateAIReviewSuggestionStatusAction(
  _previousState: AIReviewOperationActionState,
  formData: FormData
): Promise<AIReviewOperationActionState> {
  const requestId = positiveIntegerFromForm(formData, "request_id");
  const suggestionId = positiveIntegerFromForm(formData, "suggestion_id");
  if (!requestId) {
    return blockedState("invalid_ai_review_request_id", "AIReviewRequest ID 不合法。");
  }
  if (!suggestionId) {
    return blockedState("invalid_ai_review_suggestion_id", "AIReviewSuggestion ID 不合法。");
  }

  const newStatus = String(formData.get("new_status") ?? "").trim();
  const decisionNote = String(formData.get("decision_note") ?? "").trim();
  const traceId = String(formData.get("trace_id") ?? "").trim();
  if (!newStatus) {
    return blockedState("ai_review_suggestion_status_required", "请选择建议的新状态。");
  }
  if (newStatus !== "pending_review" && !decisionNote) {
    return blockedState("suggestion_decision_note_required", "除 pending_review 外，更新建议状态必须填写人工说明。");
  }

  const result = await opsPost<Record<string, unknown>>(`/api/ops/ai-review/suggestions/${suggestionId}/status/`, {
    new_status: newStatus,
    decision_note: decisionNote,
    trace_id: traceId || undefined
  });
  revalidatePath(`/ai-review/${requestId}`);
  return stateFromResult(result, "AIReviewSuggestion 状态已更新。");
}
