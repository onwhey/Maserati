"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

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

function generateReleaseCode() {
  const now = new Date();
  const timestamp = [
    now.getUTCFullYear(),
    String(now.getUTCMonth() + 1).padStart(2, "0"),
    String(now.getUTCDate()).padStart(2, "0"),
    String(now.getUTCHours()).padStart(2, "0"),
    String(now.getUTCMinutes()).padStart(2, "0"),
    String(now.getUTCSeconds()).padStart(2, "0")
  ].join("");
  const random = Math.random().toString(36).slice(2, 8);
  return `strategy-release-${timestamp}-${random}`;
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
  const isStrategy = componentType === "strategy_definition";
  const isMarketRegime = componentType === "market_regime_definition";
  const isSelectedVersion = Boolean(component.workspace_is_selected_version);
  const workspaceItemId = Number(component.workspace_item_id ?? 0);
  const upsertFormRef = useRef<HTMLFormElement>(null);
  const removeFormRef = useRef<HTMLFormElement>(null);
  const pending = upsertPending || removePending;
  const checked = isFeature || isStrategy ? isSelectedVersion : isSelectedVersion && Boolean(component.workspace_is_included);
  const [checkedState, setCheckedState] = useState(checked);
  const label = isFeature
    ? "采用此版本"
    : isStrategy
      ? "选择此版本"
      : isMarketRegime
        ? checked
          ? "当前使用"
          : "使用此算法"
        : "纳入当前组合";

  useEffect(() => {
    setCheckedState(checked);
  }, [checked]);

  function submitChange(checkedNow: boolean) {
    setCheckedState(checkedNow);
    if ((isFeature || isStrategy) && !checkedNow && isSelectedVersion && workspaceItemId) {
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
            type={isMarketRegime ? "radio" : "checkbox"}
            name="is_included"
            checked={checkedState}
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

export function WorkspaceRoutePolicyRadioForm({
  component,
  layerPath
}: {
  component: Record<string, unknown>;
  layerPath?: string;
}) {
  const router = useRouter();
  const [upsertState, upsertAction, upsertPending] = useActionState(
    upsertStrategyWorkspaceItemAction,
    initialStrategyReleaseActionState
  );
  const componentType = String(component.component_type ?? "");
  const componentObjectId = String(component.component_object_id ?? "");
  const componentCode = String(component.component_code ?? "");
  const checked = Boolean(component.workspace_is_selected_version) && Boolean(component.workspace_is_included);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (upsertState.ok && upsertState.reason_code) {
      router.refresh();
    }
  }, [router, upsertState.ok, upsertState.reason_code]);

  return (
    <div className="space-y-1.5">
      <form ref={formRef} action={upsertAction} className="flex flex-wrap items-center justify-end gap-2">
        <input type="hidden" name="component_selection" value={`${componentType}|${componentObjectId}`} />
        <input type="hidden" name="layer_path" value={layerPath ?? ""} />
        <input type="hidden" name="reason" value={`选择 ${componentType}/${componentCode}`} />
        <input type="hidden" name="confirm_write" value="on" />
        <input type="hidden" name="is_included" value="on" />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="radio"
            name="strategy_route_policy_selection"
            checked={checked}
            disabled={upsertPending}
            onChange={() => {
              if (!checked) {
                formRef.current?.requestSubmit();
              }
            }}
          />
          <span>{upsertPending ? "保存中..." : checked ? "当前使用" : "使用此路由"}</span>
        </label>
        <ActionResult state={upsertState} />
      </form>
    </div>
  );
}

export function WorkspaceSingleChoiceComponentRadioForm({
  checked,
  checkedLabel = "当前使用",
  component,
  layerPath,
  uncheckedLabel = "使用此项"
}: {
  checked: boolean;
  checkedLabel?: string;
  component: Record<string, unknown>;
  layerPath?: string;
  uncheckedLabel?: string;
}) {
  const router = useRouter();
  const [upsertState, upsertAction, upsertPending] = useActionState(
    upsertStrategyWorkspaceItemAction,
    initialStrategyReleaseActionState
  );
  const componentType = String(component.component_type ?? "");
  const componentObjectId = String(component.component_object_id ?? "");
  const componentCode = String(component.component_code ?? "");
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (upsertState.ok && upsertState.reason_code) {
      router.refresh();
    }
  }, [router, upsertState.ok, upsertState.reason_code]);

  return (
    <div className="space-y-1.5">
      <form ref={formRef} action={upsertAction} className="flex flex-wrap items-center justify-end gap-2">
        <input type="hidden" name="component_selection" value={`${componentType}|${componentObjectId}`} />
        <input type="hidden" name="layer_path" value={layerPath ?? ""} />
        <input type="hidden" name="reason" value={`选择 ${componentType}/${componentCode}`} />
        <input type="hidden" name="confirm_write" value="on" />
        <input type="hidden" name="is_included" value="on" />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="radio"
            name={`${componentType}_single_choice`}
            checked={checked}
            disabled={upsertPending}
            onChange={() => {
              if (!checked) {
                formRef.current?.requestSubmit();
              }
            }}
          />
          <span>{upsertPending ? "保存中..." : checked ? checkedLabel : uncheckedLabel}</span>
        </label>
        <ActionResult state={upsertState} />
      </form>
    </div>
  );
}

export function GenerateReleaseFromWorkspaceForm() {
  const [state, formAction, pending] = useActionState(
    generateStrategyReleaseFromWorkspaceAction,
    initialStrategyReleaseActionState
  );
  const [releaseCode, setReleaseCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    setReleaseCode(generateReleaseCode());
  }, []);

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
            <Input
              id="release_code"
              name="release_code"
              placeholder="系统自动生成"
              readOnly
              value={releaseCode}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="display_name">展示名称</Label>
            <Input
              id="display_name"
              name="display_name"
              placeholder="例如：P0 趋势策略配置"
              value={displayName}
              onChange={(event) => setDisplayName(event.currentTarget.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">说明</Label>
            <Input
              id="description"
              name="description"
              placeholder="说明本次配置的策略范围"
              value={description}
              onChange={(event) => setDescription(event.currentTarget.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">生成原因</Label>
            <Input
              id="reason"
              name="reason"
              placeholder="例如：采纳当前组件配置进入回测验证"
              value={reason}
              onChange={(event) => setReason(event.currentTarget.value)}
            />
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
