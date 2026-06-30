"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ClipboardList,
  Database,
  FileText,
  GitBranch,
  History,
  ListChecks,
  LogOut,
  ShieldCheck,
  Wrench
} from "lucide-react";

import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "仪表盘", icon: Activity },
  { href: "/runs", label: "编排运行", icon: ListChecks },
  { href: "/orders", label: "订单", icon: ClipboardList },
  { href: "/account", label: "账户", icon: Database },
  { href: "/strategy-releases", label: "策略发布", icon: GitBranch },
  { href: "/review-datasets", label: "复盘数据集", icon: Database },
  { href: "/runtime-guard", label: "运行巡检", icon: AlertTriangle },
  { href: "/alerts", label: "告警", icon: FileText },
  { href: "/real-trading", label: "真实交易", icon: ShieldCheck },
  { href: "/ops-actions", label: "运维操作", icon: Wrench },
  { href: "/audit-log", label: "审计日志", icon: History }
];

export function AppShell({
  children,
  logoutAction
}: {
  children: ReactNode;
  logoutAction: () => void | Promise<void>;
}) {
  const pathname = usePathname();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r bg-card/80 p-4 backdrop-blur lg:flex">
        <div className="mb-6 rounded-xl border bg-muted/60 p-4 text-foreground">
          <div className="text-lg font-semibold">OpsConsole</div>
          <div className="mt-1 text-xs text-muted-foreground">受控运维后台 · UTC</div>
        </div>
        <nav className="space-y-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-muted text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <form action={logoutAction} className="mt-auto pt-4">
          <button
            type="submit"
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </form>
      </aside>
      <main className="lg:pl-64">
        <div className="border-b bg-card/80 px-5 py-3 backdrop-blur lg:hidden">
          <div className="flex items-center justify-between gap-4">
            <div className="font-semibold">OpsConsole</div>
            <form action={logoutAction}>
              <button
                type="submit"
                className="inline-flex items-center gap-2 rounded-md border px-3 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <LogOut className="h-4 w-4" />
                退出登录
              </button>
            </form>
          </div>
          <div className="mt-2 flex gap-2 overflow-x-auto text-sm">
            {navigation.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "whitespace-nowrap rounded-md bg-muted/60 px-3 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    active && "bg-muted text-foreground"
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
        <div className="mx-auto max-w-7xl p-5 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
