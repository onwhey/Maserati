import * as React from "react";
import { Slot } from "@radix-ui/react-slot";

import { cn } from "@/lib/utils";

export function Button({
  className,
  asChild = false,
  variant = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  asChild?: boolean;
  variant?: "default" | "secondary" | "outline";
}) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-md px-3 text-sm font-medium transition-colors",
        variant === "default" && "bg-slate-950 text-white hover:bg-slate-800",
        variant === "secondary" && "bg-slate-100 text-slate-900 hover:bg-slate-200",
        variant === "outline" && "border bg-white hover:bg-slate-50",
        className
      )}
      {...props}
    />
  );
}
