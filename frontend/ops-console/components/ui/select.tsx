import * as React from "react";

import { cn } from "@/lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("h-9 rounded-md border bg-white px-3 py-1 text-sm shadow-sm outline-none focus:ring-2 focus:ring-slate-300", className)}
      {...props}
    />
  );
}
