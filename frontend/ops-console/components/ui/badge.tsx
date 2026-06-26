import * as React from "react";

import { cn } from "@/lib/utils";

const toneClass: Record<string, string> = {
  default: "border-transparent bg-primary text-primary-foreground",
  muted: "border-transparent bg-muted text-muted-foreground",
  green: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
  amber: "border-amber-500/30 bg-amber-500/15 text-amber-300",
  red: "border-red-500/30 bg-red-500/15 text-red-300",
  blue: "border-blue-500/30 bg-blue-500/15 text-blue-300"
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
