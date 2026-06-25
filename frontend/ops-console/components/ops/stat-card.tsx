import { type LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  helper,
  icon: Icon
}: {
  label: string;
  value: string | number;
  helper?: string;
  icon?: LucideIcon;
}) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div>
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="mt-2 text-2xl font-semibold">{value}</div>
          {helper ? <div className="mt-1 text-xs text-muted-foreground">{helper}</div> : null}
        </div>
        {Icon ? (
          <div className="rounded-lg bg-slate-100 p-2 text-slate-700">
            <Icon className="h-5 w-5" />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
