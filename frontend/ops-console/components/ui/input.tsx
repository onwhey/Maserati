import * as React from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-md border bg-white px-3 py-1 text-sm shadow-sm outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-slate-300",
        className
      )}
      {...props}
    />
  );
}
