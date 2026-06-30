"use server";

import { revalidatePath } from "next/cache";

import { opsPost } from "@/lib/api/client";
import type { OpsApiResponse } from "@/lib/api/types";

import type { StrategyReleaseActionState } from "../strategy-releases/state";

function stateFromResult(result: OpsApiResponse<Record<string, unknown>>): StrategyReleaseActionState {
  if (!result.ok) {
    return {
      ok: false,
      reason_code: result.reason_code,
      message: result.message_zh,
      release_id: null
    };
  }
  return {
    ok: true,
    reason_code: String(result.data.reason_code ?? result.reason_code),
    message: String(result.data.message ?? "操作已完成。"),
    release_id: Number(result.data.release_id ?? 0) || null
  };
}

function confirmWrite(formData: FormData): boolean {
  return formData.get("confirm_write") === "on";
}

function requiredText(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

function revalidateStrategyWorkspacePages(layerPath?: string, releaseId?: number) {
  revalidatePath("/strategy-components");
  revalidatePath("/strategy-releases");
  if (layerPath) {
    revalidatePath(`/strategy-components/${layerPath}`);
  }
  if (releaseId) {
    revalidatePath(`/strategy-releases/${releaseId}`);
  }
}

export async function upsertStrategyWorkspaceItemAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const [componentType, componentObjectId] = requiredText(formData, "component_selection").split("|");
  const result = await opsPost<Record<string, unknown>>("/api/ops/strategy-workspace/items/upsert/", {
    confirm_write: confirmWrite(formData),
    component_type: componentType,
    component_object_id: Number(componentObjectId ?? 0),
    is_included: formData.get("is_included") === "on",
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyWorkspacePages(requiredText(formData, "layer_path"));
  }
  return stateFromResult(result);
}

export async function removeStrategyWorkspaceItemAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const result = await opsPost<Record<string, unknown>>("/api/ops/strategy-workspace/items/remove/", {
    confirm_write: confirmWrite(formData),
    item_id: Number(formData.get("item_id") ?? 0),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyWorkspacePages(requiredText(formData, "layer_path"));
  }
  return stateFromResult(result);
}

type BulkWorkspaceOperation = {
  action: "upsert" | "remove";
  component_type?: string;
  component_object_id?: number;
  item_id?: number;
  is_included?: boolean;
  reason?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseBulkOperations(rawValue: FormDataEntryValue | null): BulkWorkspaceOperation[] {
  if (typeof rawValue !== "string" || rawValue.trim().length === 0) {
    return [];
  }
  const parsed: unknown = JSON.parse(rawValue);
  if (!Array.isArray(parsed)) {
    return [];
  }
  return parsed.filter(isRecord).flatMap((item) => {
    const action = item.action === "remove" ? "remove" : item.action === "upsert" ? "upsert" : "";
    if (!action) {
      return [];
    }
    return [
      {
        action,
        component_type: typeof item.component_type === "string" ? item.component_type : undefined,
        component_object_id: Number(item.component_object_id ?? 0) || undefined,
        item_id: Number(item.item_id ?? 0) || undefined,
        is_included: item.is_included === true,
        reason: typeof item.reason === "string" ? item.reason : ""
      }
    ];
  });
}

export async function bulkUpdateStrategyWorkspaceItemsAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const mode = requiredText(formData, "bulk_mode");
  let operations: BulkWorkspaceOperation[] = [];
  try {
    operations = parseBulkOperations(formData.get(`operations_${mode}`));
  } catch {
    return {
      ok: false,
      reason_code: "strategy_workspace_bulk_payload_invalid",
      message: "批量操作参数不合法。",
      release_id: null
    };
  }

  if (!operations.length) {
    return {
      ok: true,
      reason_code: "strategy_workspace_bulk_noop",
      message: "当前筛选结果没有需要处理的组件。",
      release_id: null
    };
  }

  let successCount = 0;
  for (const operation of operations) {
    const result =
      operation.action === "remove"
        ? await opsPost<Record<string, unknown>>("/api/ops/strategy-workspace/items/remove/", {
            confirm_write: true,
            item_id: operation.item_id ?? 0,
            reason: operation.reason || "批量移除当前策略配置项"
          })
        : await opsPost<Record<string, unknown>>("/api/ops/strategy-workspace/items/upsert/", {
            confirm_write: true,
            component_type: operation.component_type ?? "",
            component_object_id: operation.component_object_id ?? 0,
            is_included: operation.is_included === true,
            reason: operation.reason || "批量更新当前策略配置项"
          });

    if (!result.ok) {
      revalidateStrategyWorkspacePages(requiredText(formData, "layer_path"));
      return {
        ok: false,
        reason_code: result.reason_code,
        message: `批量操作已完成 ${successCount} 项，随后失败：${result.message_zh}`,
        release_id: null
      };
    }
    successCount += 1;
  }

  revalidateStrategyWorkspacePages(requiredText(formData, "layer_path"));
  return {
    ok: true,
    reason_code: "strategy_workspace_bulk_updated",
    message: `批量操作完成，共处理 ${successCount} 项。`,
    release_id: null
  };
}

export async function generateStrategyReleaseFromWorkspaceAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const result = await opsPost<Record<string, unknown>>("/api/ops/strategy-workspace/generate-release/", {
    confirm_write: confirmWrite(formData),
    release_code: requiredText(formData, "release_code"),
    display_name: requiredText(formData, "display_name"),
    description: requiredText(formData, "description"),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyWorkspacePages(undefined, Number(result.data.release_id ?? 0) || undefined);
  }
  return stateFromResult(result);
}
