"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatUtc } from "@/lib/utils";

type ChartPoint = {
  period: string;
  pnl: number;
};

function toChartPoints(rows: Array<Record<string, unknown>>): ChartPoint[] {
  return rows
    .filter((row) => row.calculation_status === "calculated")
    .map((row) => ({
      period: String(row.period_end_utc ?? ""),
      pnl: Number(row.cycle_floating_pnl)
    }))
    .filter((point) => point.period && Number.isFinite(point.pnl))
    .reverse();
}

export function PerformancePnlChart({ rows }: { rows: Array<Record<string, unknown>> }) {
  const data = toChartPoints(rows);
  if (data.length === 0) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">暂无已计算的周期浮动收益记录</div>;
  }

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <XAxis dataKey="period" tickFormatter={(value) => formatUtc(value).slice(5, 16)} />
          <YAxis />
          <Tooltip
            labelFormatter={(value) => formatUtc(value)}
            formatter={(value) => [String(value), "cycle_floating_pnl"]}
          />
          <Line type="monotone" dataKey="pnl" stroke="#0f172a" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
