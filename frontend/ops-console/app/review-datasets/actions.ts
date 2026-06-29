"use server";

import { opsPost } from "@/lib/api/client";

type ReviewDatasetExportActionState = {
  ok: boolean;
  reason_code: string;
  message: string;
  export_id: number | null;
};

export const initialReviewDatasetExportState: ReviewDatasetExportActionState = {
  ok: false,
  reason_code: "",
  message: "",
  export_id: null
};

export async function createReviewDatasetExportAction(
  _previousState: ReviewDatasetExportActionState,
  formData: FormData
): Promise<ReviewDatasetExportActionState> {
  const rawIds = String(formData.get("orchestration_run_ids") ?? "").trim();
  const reason = String(formData.get("reason") ?? "").trim();
  const exportFormat = String(formData.get("export_format") ?? "json").trim() || "json";
  const confirmWrite = formData.get("confirm_write") === "on";
  const ids = rawIds
    .split(/[,\s]+/)
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value > 0);

  if (ids.length === 0) {
    return {
      ok: false,
      reason_code: "review_dataset_run_ids_required",
      message: "请填写至少一个 OrchestrationRun ID。",
      export_id: null
    };
  }
  if (!reason) {
    return {
      ok: false,
      reason_code: "review_dataset_reason_required",
      message: "ReviewDataset 导出必须填写原因。",
      export_id: null
    };
  }
  if (!confirmWrite) {
    return {
      ok: false,
      reason_code: "review_dataset_confirm_write_required",
      message: "请勾选确认写入导出记录。",
      export_id: null
    };
  }

  const result = await opsPost<Record<string, unknown>>("/api/ops/review-datasets/exports/create/", {
    confirm_write: true,
    reason,
    range_selector: { type: "run_ids", ids },
    filters: {},
    export_format: exportFormat
  });
  if (!result.ok) {
    return {
      ok: false,
      reason_code: result.reason_code,
      message: result.message_zh,
      export_id: null
    };
  }
  return {
    ok: true,
    reason_code: String(result.data.reason_code ?? result.reason_code),
    message: String(result.data.message ?? "ReviewDataset 导出已创建。"),
    export_id: Number(result.data.export_id ?? 0) || null
  };
}
