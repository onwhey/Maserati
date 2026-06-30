"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { asRows } from "@/lib/ops-data";

import {
  activateStrategyReleaseAction,
  addStrategyReleaseEvidenceAction,
  approveStrategyReleaseAction,
  copyStrategyReleaseDraftAction,
  createStrategyReleaseDraftAction,
  freezeStrategyReleaseAction,
  initialStrategyReleaseActionState,
  invalidateStrategyReleaseAction,
  prevalidateStrategyReleaseAction,
  rejectStrategyReleaseAction,
  removeStrategyReleaseItemAction,
  rollbackStrategyReleaseAction,
  updateStrategyReleaseDraftAction,
  upsertStrategyReleaseItemAction
} from "./actions";

function ActionResult({ state }: { state: typeof initialStrategyReleaseActionState }) {
  if (!state.reason_code) {
    return null;
  }
  return (
    <div className={state.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}>
      {state.message} {state.release_id ? `Release ID：${state.release_id}` : ""}
    </div>
  );
}

function ConfirmWrite() {
  return (
    <label className="flex items-start gap-2 text-sm text-muted-foreground">
      <input className="mt-1" type="checkbox" name="confirm_write" />
      <span>我确认这是受控后台写入操作，会写审计记录，不会触发交易执行。</span>
    </label>
  );
}

export function CreateDraftForm() {
  const [state, formAction, pending] = useActionState(createStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  return (
    <Card>
      <CardHeader>
        <CardTitle>创建 draft 版本包</CardTitle>
        <CardDescription>只创建可编辑草稿，不会进入正式主链路。</CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="release_code">版本包代码</Label>
            <Input id="release_code" name="release_code" placeholder="例如：strategy-release-2026-06-30-a" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="display_name">展示名称</Label>
            <Input id="display_name" name="display_name" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">说明</Label>
            <Input id="description" name="description" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">原因</Label>
            <Input id="reason" name="reason" placeholder="例如：组装第一版正式策略分析包" />
          </div>
          <ConfirmWrite />
          <Button type="submit" disabled={pending}>
            {pending ? "创建中..." : "创建草稿"}
          </Button>
          <ActionResult state={state} />
        </form>
      </CardContent>
    </Card>
  );
}

export function DraftEditForms({
  release,
  components
}: {
  release: Record<string, unknown>;
  components: unknown;
}) {
  const releaseId = Number(release.id ?? 0);
  const componentRows = asRows(components);
  const [updateState, updateAction, updatePending] = useActionState(updateStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  const [upsertState, upsertAction, upsertPending] = useActionState(upsertStrategyReleaseItemAction, initialStrategyReleaseActionState);
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>编辑 draft 说明</CardTitle>
          <CardDescription>只有 draft 状态允许原地修改展示信息。</CardDescription>
        </CardHeader>
        <CardContent>
          <form action={updateAction} className="space-y-4">
            <input type="hidden" name="release_id" value={releaseId} />
            <div className="space-y-2">
              <Label htmlFor="display_name">展示名称</Label>
              <Input id="display_name" name="display_name" defaultValue={String(release.display_name ?? "")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">说明</Label>
              <Input id="description" name="description" defaultValue={String(release.description ?? "")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reason">原因</Label>
              <Input id="reason" name="reason" placeholder="例如：补充版本包说明" />
            </div>
            <ConfirmWrite />
            <Button type="submit" disabled={updatePending}>
              {updatePending ? "保存中..." : "保存草稿说明"}
            </Button>
            <ActionResult state={updateState} />
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>加入或替换组件</CardTitle>
          <CardDescription>同一组件代码只能保留一个版本；再次选择会替换草稿中的旧版本。</CardDescription>
        </CardHeader>
        <CardContent>
          <form action={upsertAction} className="space-y-4">
            <input type="hidden" name="release_id" value={releaseId} />
            <div className="space-y-2">
              <Label htmlFor="component_selection">组件</Label>
              <Select id="component_selection" name="component_selection" defaultValue="">
                <option value="" disabled>
                  选择已登记组件
                </option>
                {componentRows.map((component) => (
                  <option
                    key={`${component.component_type}|${component.component_object_id}`}
                    value={`${component.component_type}|${component.component_object_id}`}
                  >
                    {String(component.component_type)} / {String(component.component_code)} / {String(component.version ?? "")}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="reason">原因</Label>
              <Input id="reason" name="reason" placeholder="例如：加入趋势领域 v1 定义" />
            </div>
            <ConfirmWrite />
            <Button type="submit" disabled={upsertPending}>
              {upsertPending ? "写入中..." : "写入组件"}
            </Button>
            <ActionResult state={upsertState} />
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export function CopyDraftForm({ release }: { release: Record<string, unknown> }) {
  const releaseId = Number(release.id ?? 0);
  const [state, formAction, pending] = useActionState(copyStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  return (
    <Card>
      <CardHeader>
        <CardTitle>复制为新 draft</CardTitle>
        <CardDescription>修改已冻结或已批准版本包时，必须复制成新草稿重新走完整流程。</CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          <input type="hidden" name="release_id" value={releaseId} />
          <div className="space-y-2">
            <Label htmlFor="release_code">新版本包代码</Label>
            <Input id="release_code" name="release_code" placeholder={`copy-of-${String(release.release_code ?? "")}`} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="display_name">展示名称</Label>
            <Input id="display_name" name="display_name" placeholder="新草稿展示名称" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">说明</Label>
            <Input id="description" name="description" placeholder="说明复制目的" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">原因</Label>
            <Input id="reason" name="reason" placeholder="例如：基于当前版本调整某个组件版本" />
          </div>
          <ConfirmWrite />
          <Button type="submit" variant="outline" disabled={pending}>
            {pending ? "复制中..." : "复制为 draft"}
          </Button>
          <ActionResult state={state} />
        </form>
      </CardContent>
    </Card>
  );
}

export function RemoveItemForm({ releaseId, itemId }: { releaseId: number; itemId: number }) {
  const [state, formAction, pending] = useActionState(removeStrategyReleaseItemAction, initialStrategyReleaseActionState);
  return (
    <form action={formAction} className="flex min-w-52 items-center gap-2">
      <input type="hidden" name="release_id" value={releaseId} />
      <input type="hidden" name="item_id" value={itemId} />
      <input type="hidden" name="reason" value="从 draft 移除组件" />
      <input type="hidden" name="confirm_write" value="on" />
      <Button type="submit" variant="outline" disabled={pending}>
        移除
      </Button>
      <ActionResult state={state} />
    </form>
  );
}

export function ReleaseStateActionForms({ release }: { release: Record<string, unknown> }) {
  const releaseId = Number(release.id ?? 0);
  const [prevalidateState, prevalidateAction, prevalidatePending] = useActionState(
    prevalidateStrategyReleaseAction,
    initialStrategyReleaseActionState
  );
  const [freezeState, freezeAction, freezePending] = useActionState(freezeStrategyReleaseAction, initialStrategyReleaseActionState);
  const [evidenceState, evidenceAction, evidencePending] = useActionState(
    addStrategyReleaseEvidenceAction,
    initialStrategyReleaseActionState
  );
  const [approveState, approveAction, approvePending] = useActionState(approveStrategyReleaseAction, initialStrategyReleaseActionState);
  const [activateState, activateAction, activatePending] = useActionState(activateStrategyReleaseAction, initialStrategyReleaseActionState);
  const [rejectState, rejectAction, rejectPending] = useActionState(rejectStrategyReleaseAction, initialStrategyReleaseActionState);
  const [invalidateState, invalidateAction, invalidatePending] = useActionState(
    invalidateStrategyReleaseAction,
    initialStrategyReleaseActionState
  );
  const [rollbackState, rollbackAction, rollbackPending] = useActionState(rollbackStrategyReleaseAction, initialStrategyReleaseActionState);

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>校验与冻结</CardTitle>
          <CardDescription>预校验只提示缺口；冻结后组件不可原地修改。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form action={prevalidateAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Button type="submit" variant="outline" disabled={prevalidatePending}>
              {prevalidatePending ? "校验中..." : "依赖闭包预校验"}
            </Button>
            <ActionResult state={prevalidateState} />
          </form>
          <form action={freezeAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="冻结原因" />
            <ConfirmWrite />
            <Button type="submit" disabled={freezePending}>
              {freezePending ? "冻结中..." : "冻结进入 validating"}
            </Button>
            <ActionResult state={freezeState} />
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>验证证据、批准与启用</CardTitle>
          <CardDescription>批准不会自动启用；启用只影响后续新编排。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form action={evidenceAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="evidence_type" placeholder="证据类型，例如 backtest" />
            <Input name="evidence_ref" placeholder="证据引用，例如 本地回测报告路径" />
            <Input name="summary" placeholder="证据摘要" />
            <Input name="reason" placeholder="登记证据原因" />
            <ConfirmWrite />
            <Button type="submit" disabled={evidencePending}>
              {evidencePending ? "登记中..." : "登记验证证据"}
            </Button>
            <ActionResult state={evidenceState} />
          </form>
          <form action={approveAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="批准原因" />
            <ConfirmWrite />
            <Button type="submit" variant="outline" disabled={approvePending}>
              {approvePending ? "批准中..." : "批准版本包"}
            </Button>
            <ActionResult state={approveState} />
          </form>
          <form action={rejectAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="拒绝原因" />
            <ConfirmWrite />
            <Button type="submit" variant="outline" disabled={rejectPending}>
              {rejectPending ? "拒绝中..." : "拒绝 validating 版本包"}
            </Button>
            <ActionResult state={rejectState} />
          </form>
          <form action={activateAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="启用原因" />
            <ConfirmWrite />
            <Button type="submit" variant="outline" disabled={activatePending}>
              {activatePending ? "启用中..." : "启用为当前版本包"}
            </Button>
            <ActionResult state={activateState} />
          </form>
          <form action={rollbackAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="回滚原因" />
            <ConfirmWrite />
            <Button type="submit" variant="outline" disabled={rollbackPending}>
              {rollbackPending ? "回滚中..." : "回滚到此版本包"}
            </Button>
            <ActionResult state={rollbackState} />
          </form>
          <form action={invalidateAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="失效原因" />
            <ConfirmWrite />
            <Button type="submit" variant="outline" disabled={invalidatePending}>
              {invalidatePending ? "失效中..." : "失效 approved/active 版本包"}
            </Button>
            <ActionResult state={invalidateState} />
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
