"use server";

import { redirect } from "next/navigation";

import { opsPost } from "@/lib/api/client";

type StrategyBacktestActionState = {
  ok: boolean;
  reason_code: string;
  message: string;
  data: Record<string, unknown> | null;
};

export async function runStrategyBacktestAction(
  _previousState: StrategyBacktestActionState,
  formData: FormData
): Promise<StrategyBacktestActionState> {
  const releaseValue = String(formData.get("release") ?? "").trim();
  const [releaseIdText, releaseHash = ""] = releaseValue.split("|");
  const releaseId = Number(releaseIdText);
  const start = normalizeUtcDateTimeInput(String(formData.get("start_analysis_close_time_utc") ?? ""));
  const end = normalizeUtcDateTimeInput(String(formData.get("end_analysis_close_time_utc") ?? ""));
  const initialEquity = String(formData.get("initial_equity") ?? "10000").trim() || "10000";
  const feeRate = String(formData.get("fee_rate") ?? "0.0004").trim() || "0.0004";
  const leverage = String(formData.get("leverage") ?? "1").trim() || "1";
  const lookback4h = Number(formData.get("lookback_4h_count") ?? 500);
  const lookback1d = Number(formData.get("lookback_1d_count") ?? 500);
  const noTargetPolicy = String(formData.get("no_target_policy") ?? "hold").trim() || "hold";

  if (!Number.isInteger(releaseId) || releaseId <= 0) {
    return {
      ok: false,
      reason_code: "strategy_backtest_release_required",
      message: "请选择策略版本包。",
      data: null
    };
  }
  if (!start || !end) {
    return {
      ok: false,
      reason_code: "strategy_backtest_time_range_required",
      message: "请选择 UTC 起止日期。",
      data: null
    };
  }

  const result = await opsPost<Record<string, unknown>>("/api/ops/strategy-backtests/runs/create/", {
    strategy_analysis_release_id: releaseId,
    strategy_analysis_release_hash: releaseHash,
    start_analysis_close_time_utc: start,
    end_analysis_close_time_utc: end,
    initial_equity: initialEquity,
    fee_rate: feeRate,
    leverage,
    lookback_4h_count: lookback4h,
    lookback_1d_count: lookback1d,
    no_target_policy: noTargetPolicy,
    business_request_prefix: "ops-strategy-backtest"
  });

  if (!result.ok) {
    return {
      ok: false,
      reason_code: result.reason_code,
      message: result.message_zh,
      data: null
    };
  }

  const runId = String(result.data.strategy_backtest_run_id ?? "");
  if (runId) {
    redirect(`/strategy-backtests/${encodeURIComponent(runId)}`);
  }
  return {
    ok: false,
    reason_code: "strategy_backtest_run_id_missing",
    message: "回测任务已提交，但后端没有返回运行记录 ID。",
    data: null
  };
}

function normalizeUtcDateTimeInput(rawValue: string): string {
  const value = rawValue.trim();
  if (!value) {
    return "";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return `${value}T00:00:00+00:00`;
  }
  if (/[zZ]$/.test(value) || /[+-]\d{2}:\d{2}$/.test(value)) {
    return value;
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) {
    return `${value}:00+00:00`;
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(value)) {
    return `${value}+00:00`;
  }
  return value;
}
