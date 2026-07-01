"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

import { runStrategyBacktestAction } from "./actions";

type ReleaseRow = Record<string, unknown>;
type StrategyBacktestActionState = {
  ok: boolean;
  reason_code: string;
  message: string;
  data: Record<string, unknown> | null;
};

const initialStrategyBacktestState: StrategyBacktestActionState = {
  ok: false,
  reason_code: "",
  message: "",
  data: null
};

export function StrategyBacktestForm({ releases }: { releases: ReleaseRow[] }) {
  const [state, formAction, pending] = useActionState(runStrategyBacktestAction, initialStrategyBacktestState);

  return (
    <Card>
      <CardHeader>
        <CardTitle>创建收益回测任务</CardTitle>
        <CardDescription>
          点击后只创建后台任务；页面会跳到运行记录，可以刷新页面查看进度。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="release" className="block">策略版本包</Label>
            <Select id="release" name="release" className="w-full" required>
              <option value="">请选择版本包</option>
              {releases.map((release) => (
                <option
                  key={String(release.id)}
                  value={`${String(release.id)}|${String(release.release_hash ?? "")}`}
                >
                  #{String(release.id)} {String(release.display_name || release.release_code || "")}
                  {release.is_active ? "（当前启用）" : ""}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="start_analysis_close_time_utc">开始日期（UTC）</Label>
            <Input
              id="start_analysis_close_time_utc"
              name="start_analysis_close_time_utc"
              type="date"
              required
            />
            <p className="text-xs text-muted-foreground">例如选择 2026-06-01，表示从 2026-06-01 00:00 UTC 这根 4h K 线开始。</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="end_analysis_close_time_utc">结束日期（UTC）</Label>
            <Input
              id="end_analysis_close_time_utc"
              name="end_analysis_close_time_utc"
              type="date"
              required
            />
            <p className="text-xs text-muted-foreground">例如选择 2026-07-01，表示截止到 2026-07-01 00:00 UTC 开盘的这根 4h K 线。</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="initial_equity">初始资金</Label>
              <Input id="initial_equity" name="initial_equity" defaultValue="10000" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="fee_rate">单边手续费率</Label>
              <Input id="fee_rate" name="fee_rate" defaultValue="0.0004" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="leverage">杠杆倍数</Label>
              <Input id="leverage" name="leverage" defaultValue="1" />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="lookback_4h_count">4h 回看数量</Label>
              <Input id="lookback_4h_count" name="lookback_4h_count" defaultValue="500" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="lookback_1d_count">1d 回看数量</Label>
              <Input id="lookback_1d_count" name="lookback_1d_count" defaultValue="500" />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="no_target_policy" className="block">无目标仓位时</Label>
            <Select id="no_target_policy" name="no_target_policy" className="w-full" defaultValue="hold">
              <option value="hold">维持上一周期仓位</option>
              <option value="flat">按空仓处理</option>
            </Select>
          </div>

          <Button type="submit" disabled={pending}>
            {pending ? "创建任务中..." : "开始回测"}
          </Button>
          {state.reason_code ? (
            <div className={state.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}>{state.message}</div>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}
