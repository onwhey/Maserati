"use client";

import { useActionState, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  generateStrategyReleaseFromWorkspaceAction,
  removeStrategyWorkspaceItemAction,
  upsertStrategyWorkspaceItemAction
} from "./actions";
import { initialStrategyReleaseActionState } from "../strategy-releases/state";

function ActionResult({ state }: { state: typeof initialStrategyReleaseActionState }) {
  if (!state.reason_code) {
    return null;
  }
  return (
    <div className={state.ok ? "text-xs text-emerald-600" : "text-xs text-destructive"}>
      {state.message} {state.release_id ? `Release ID：${state.release_id}` : ""}
    </div>
  );
}

export function WorkspaceComponentActionForm({
  component,
  layerPath
}: {
  component: Record<string, unknown>;
  layerPath?: string;
}) {
  const [upsertState, upsertAction, upsertPending] = useActionState(
    upsertStrategyWorkspaceItemAction,
    initialStrategyReleaseActionState
  );
  const [removeState, removeAction, removePending] = useActionState(
    removeStrategyWorkspaceItemAction,
    initialStrategyReleaseActionState
  );
  const componentType = String(component.component_type ?? "");
  const componentObjectId = String(component.component_object_id ?? "");
  const componentCode = String(component.component_code ?? "");
  const isFeature = componentType === "feature_definition";
  const isSelectedVersion = Boolean(component.workspace_is_selected_version);
  const workspaceItemId = Number(component.workspace_item_id ?? 0);
  const upsertFormRef = useRef<HTMLFormElement>(null);
  const removeFormRef = useRef<HTMLFormElement>(null);
  const pending = upsertPending || removePending;
  const checked = isFeature ? isSelectedVersion : isSelectedVersion && Boolean(component.workspace_is_included);
  const label = isFeature ? "采用此版本" : "纳入当前组合";

  function submitChange(checkedNow: boolean) {
    if (isFeature && !checkedNow && isSelectedVersion && workspaceItemId) {
      removeFormRef.current?.requestSubmit();
      return;
    }
    upsertFormRef.current?.requestSubmit();
  }

  return (
    <div className="space-y-1.5">
      <form ref={upsertFormRef} action={upsertAction} className="flex flex-wrap items-center justify-end gap-2">
        <input type="hidden" name="component_selection" value={`${componentType}|${componentObjectId}`} />
        <input type="hidden" name="layer_path" value={layerPath ?? ""} />
        <input type="hidden" name="reason" value={`选择 ${componentType}/${componentCode}`} />
        <input type="hidden" name="confirm_write" value="on" />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            name="is_included"
            defaultChecked={checked}
            disabled={pending}
            onChange={(event) => submitChange(event.currentTarget.checked)}
          />
          <span>{pending ? "保存中..." : label}</span>
        </label>
        <ActionResult state={upsertState} />
      </form>

      <form ref={removeFormRef} action={removeAction} className="hidden">
        <input type="hidden" name="item_id" value={workspaceItemId} />
        <input type="hidden" name="layer_path" value={layerPath ?? ""} />
        <input type="hidden" name="reason" value={`移除 ${componentType}/${componentCode}`} />
        <input type="hidden" name="confirm_write" value="on" />
      </form>
      <ActionResult state={removeState} />
    </div>
  );
}

export function GenerateReleaseFromWorkspaceForm() {
  const [state, formAction, pending] = useActionState(
    generateStrategyReleaseFromWorkspaceAction,
    initialStrategyReleaseActionState
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>从当前配置生成草稿</CardTitle>
        <CardDescription>把当前策略组件配置冻结成一个新的 StrategyAnalysisRelease 草稿。</CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          <input type="hidden" name="confirm_write" value="on" />
          <div className="space-y-2">
            <Label htmlFor="release_code">版本包代码</Label>
            <Input id="release_code" name="release_code" placeholder="例如：strategy-release-p0-001" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="display_name">展示名称</Label>
            <Input id="display_name" name="display_name" placeholder="例如：P0 趋势策略配置" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">说明</Label>
            <Input id="description" name="description" placeholder="说明本次配置的策略范围" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">生成原因</Label>
            <Input id="reason" name="reason" placeholder="例如：采纳当前组件配置进入回测验证" />
          </div>
          <Button type="submit" disabled={pending}>
            {pending ? "生成中..." : "生成草稿"}
          </Button>
          <ActionResult state={state} />
        </form>
      </CardContent>
    </Card>
  );
}
