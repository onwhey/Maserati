"use client";

import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function RecentRunStatusChart({ runs }: { runs: Array<Record<string, unknown>> }) {
  const counts = runs.reduce<Record<string, number>>((acc, run) => {
    const status = String(run.status ?? "unknown");
    acc[status] = (acc[status] ?? 0) + 1;
    return acc;
  }, {});
  const data = Object.entries(counts).map(([status, count]) => ({ status, count }));

  if (data.length === 0) {
    return <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">暂无编排运行数据</div>;
  }

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="status" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Bar dataKey="count" fill="#0f172a" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
