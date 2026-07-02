"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  activateStrategyReleaseAction,
  approveStrategyReleaseAction,
  copyStrategyReleaseDraftAction,
  createStrategyReleaseDraftAction,
  freezeStrategyReleaseAction,
  invalidateStrategyReleaseAction,
  prevalidateStrategyReleaseAction,
  rejectStrategyReleaseAction,
  removeStrategyReleaseItemAction,
  rollbackStrategyReleaseAction,
  updateStrategyReleaseDraftAction
} from "./actions";
import { initialStrategyReleaseActionState } from "./state";

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
  return <input type="hidden" name="confirm_write" value="on" />;
}

export function CreateDraftForm() {
  const [state, formAction, pending] = useActionState(createStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  return (
    <Card>
      <CardHeader>
        <CardTitle>创建草稿版本包</CardTitle>
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
  release
}: {
  release: Record<string, unknown>;
}) {
  const releaseId = Number(release.id ?? 0);
  const [updateState, updateAction, updatePending] = useActionState(updateStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  return (
    <Card>
      <CardHeader>
        <CardTitle>编辑草稿说明</CardTitle>
        <CardDescription>只有草稿状态允许原地修改展示信息；组件内容应从策略组件页生成。</CardDescription>
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
          <Button type="submit" disabled={updatePending}>
            {updatePending ? "保存中..." : "保存草稿说明"}
          </Button>
          <ActionResult state={updateState} />
        </form>
      </CardContent>
    </Card>
  );
}

export function CopyDraftForm({ release }: { release: Record<string, unknown> }) {
  const releaseId = Number(release.id ?? 0);
  const [state, formAction, pending] = useActionState(copyStrategyReleaseDraftAction, initialStrategyReleaseActionState);
  return (
    <Card>
      <details className="group">
        <summary className="cursor-pointer list-none">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>复制为新草稿</CardTitle>
                <CardDescription>修改已冻结或已批准版本包时，必须复制成新草稿重新走完整流程。</CardDescription>
              </div>
              <span className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
                <span className="group-open:hidden">展开</span>
                <span className="hidden group-open:inline">收起</span>
              </span>
            </div>
          </CardHeader>
        </summary>
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
              {pending ? "复制中..." : "复制为草稿"}
            </Button>
            <ActionResult state={state} />
          </form>
        </CardContent>
      </details>
    </Card>
  );
}

export function RemoveItemForm({ releaseId, itemId }: { releaseId: number; itemId: number }) {
  const [state, formAction, pending] = useActionState(removeStrategyReleaseItemAction, initialStrategyReleaseActionState);
  return (
    <form action={formAction} className="flex min-w-52 items-center gap-2">
      <input type="hidden" name="release_id" value={releaseId} />
      <input type="hidden" name="item_id" value={itemId} />
      <input type="hidden" name="reason" value="从草稿移除组件" />
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
          <CardTitle>批准与启用</CardTitle>
          <CardDescription>批准会自动引用同版本包已完成回测作为验证证据；启用只影响后续新编排。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form action={approveAction} className="space-y-3">
            <input type="hidden" name="release_id" value={releaseId} />
            <Input name="reason" placeholder="批准原因，例如：回测结果可接受，进入候选启用" />
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
