"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function BacktestAutoRefresh({ enabled }: { enabled: boolean }) {
  const router = useRouter();

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const timer = window.setTimeout(() => {
      router.refresh();
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [enabled, router]);

  return null;
}
