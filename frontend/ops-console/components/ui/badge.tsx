import * as React from "react";

import { cn } from "@/lib/utils";

const toneClass: Record<string, string> = {
  default: "border-transparent bg-slate-900 text-white",
  muted: "border-transparent bg-slate-100 text-slate-700",
  green: "border-transparent bg-emerald-100 text-emerald-700",
  amber: "border-transparent bg-amber-100 text-amber-800",
  red: "border-transparent bg-red-100 text-red-700",
  blue: "border-transparent bg-blue-100 text-blue-700"
};

export function Badge({
  className,
  tone = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof toneClass }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        toneClass[tone],
        className
      )}
      {...props}
    />
  );
}
