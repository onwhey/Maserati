"use server";

import { opsPost } from "@/lib/api/client";
import type { OpsApiResponse } from "@/lib/api/types";
import { revalidatePath } from "next/cache";

type StrategyReleaseActionState = {
  ok: boolean;
  reason_code: string;
  message: string;
  release_id: number | null;
};

export const initialStrategyReleaseActionState: StrategyReleaseActionState = {
  ok: false,
  reason_code: "",
  message: "",
  release_id: null
};

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

function releaseId(formData: FormData): number {
  return Number(formData.get("release_id") ?? 0);
}

function revalidateStrategyReleasePages(id?: number) {
  revalidatePath("/strategy-releases");
  if (id) {
    revalidatePath(`/strategy-releases/${id}`);
  }
}

export async function createStrategyReleaseDraftAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const result = await opsPost<Record<string, unknown>>("/api/ops/strategy-releases/create-draft/", {
    confirm_write: confirmWrite(formData),
    release_code: requiredText(formData, "release_code"),
    display_name: requiredText(formData, "display_name"),
    description: requiredText(formData, "description"),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(Number(result.data.release_id ?? 0) || undefined);
  }
  return stateFromResult(result);
}

export async function updateStrategyReleaseDraftAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/update-draft/`, {
    confirm_write: confirmWrite(formData),
    display_name: requiredText(formData, "display_name"),
    description: requiredText(formData, "description"),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function copyStrategyReleaseDraftAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/copy-draft/`, {
    confirm_write: confirmWrite(formData),
    release_code: requiredText(formData, "release_code"),
    display_name: requiredText(formData, "display_name"),
    description: requiredText(formData, "description"),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(Number(result.data.release_id ?? 0) || undefined);
  }
  return stateFromResult(result);
}

export async function upsertStrategyReleaseItemAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const [componentType, componentObjectId] = requiredText(formData, "component_selection").split("|");
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/items/upsert/`, {
    confirm_write: confirmWrite(formData),
    component_type: componentType,
    component_object_id: Number(componentObjectId ?? 0),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function removeStrategyReleaseItemAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/items/remove/`, {
    confirm_write: confirmWrite(formData),
    item_id: Number(formData.get("item_id") ?? 0),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function prevalidateStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/prevalidate/`, {});
  return stateFromResult(result);
}

export async function freezeStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/freeze/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function addStrategyReleaseEvidenceAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/validation-evidence/`, {
    confirm_write: confirmWrite(formData),
    evidence_type: requiredText(formData, "evidence_type"),
    evidence_ref: requiredText(formData, "evidence_ref"),
    summary: requiredText(formData, "summary"),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function approveStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/approve/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function rejectStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/reject/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function invalidateStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/invalidate/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function activateStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/activate/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}

export async function rollbackStrategyReleaseAction(
  _previousState: StrategyReleaseActionState,
  formData: FormData
): Promise<StrategyReleaseActionState> {
  const id = releaseId(formData);
  const result = await opsPost<Record<string, unknown>>(`/api/ops/strategy-releases/${id}/rollback/`, {
    confirm_write: confirmWrite(formData),
    reason: requiredText(formData, "reason")
  });
  if (result.ok) {
    revalidateStrategyReleasePages(id);
  }
  return stateFromResult(result);
}
