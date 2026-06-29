"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

import { createReviewDatasetExportAction, initialReviewDatasetExportState } from "./actions";

export function ReviewDatasetCreateExportForm() {
  const [state, formAction, pending] = useActionState(createReviewDatasetExportAction, initialReviewDatasetExportState);

  return (
    <Card>
      <CardHeader>
        <CardTitle>创建 ReviewDataset 导出</CardTitle>
        <CardDescription>
          只选择已落库编排事实并生成离线复盘数据集；不会调用 Binance、DeepSeek，也不会影响自动交易链路。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="orchestration_run_ids">OrchestrationRun ID</Label>
            <Input id="orchestration_run_ids" name="orchestration_run_ids" placeholder="例如：101,102,103" />
            <p className="text-xs text-muted-foreground">多个 ID 可用逗号、空格或换行分隔。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="export_format">导出格式</Label>
            <Select id="export_format" name="export_format" defaultValue="json">
              <option value="json">JSON</option>
              <option value="jsonl">JSONL</option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason">操作原因</Label>
            <Input id="reason" name="reason" placeholder="例如：导出最近策略周期用于本地复盘" />
          </div>
          <label className="flex items-start gap-2 text-sm text-muted-foreground">
            <input className="mt-1" type="checkbox" name="confirm_write" />
            <span>我确认本操作会写入 ReviewDatasetExport、审计记录和导出文件，但不会修改上游业务事实。</span>
          </label>
          <Button type="submit" disabled={pending}>
            {pending ? "创建中..." : "创建导出"}
          </Button>
          {state.reason_code ? (
            <div className={state.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}>
              {state.message} {state.export_id ? `导出 ID：${state.export_id}` : ""}
            </div>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}
