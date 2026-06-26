"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  ClipboardList,
  Database,
  FileText,
  History,
  ListChecks,
  ShieldCheck,
  Wrench
} from "lucide-react";

const navigation = [
  { href: "/", label: "Dashboard", icon: Activity },
  { href: "/runs", label: "Runs", icon: ListChecks },
  { href: "/orders", label: "Orders", icon: ClipboardList },
  { href: "/account", label: "Account", icon: Database },
  { href: "/performance", label: "Performance", icon: BarChart3 },
  { href: "/runtime-guard", label: "Runtime Guard", icon: AlertTriangle },
  { href: "/alerts", label: "Alerts", icon: FileText },
  { href: "/real-trading", label: "Real Trading", icon: ShieldCheck },
  { href: "/ai-review", label: "AI Review", icon: Bot },
  { href: "/ops-actions", label: "Ops Actions", icon: Wrench },
  { href: "/audit-log", label: "Audit Log", icon: History }
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r bg-white/80 p-4 backdrop-blur lg:block">
        <div className="mb-6 rounded-xl border bg-slate-950 p-4 text-white">
          <div className="text-lg font-semibold">OpsConsole</div>
          <div className="mt-1 text-xs text-slate-300">只读事实后台 · UTC</div>
        </div>
        <nav className="space-y-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="lg:pl-64">
        <div className="border-b bg-white/70 px-5 py-3 backdrop-blur lg:hidden">
          <div className="font-semibold">OpsConsole</div>
          <div className="mt-2 flex gap-2 overflow-x-auto text-sm">
            {navigation.map((item) => (
              <Link key={item.href} href={item.href} className="whitespace-nowrap rounded-md bg-slate-100 px-3 py-1">
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="mx-auto max-w-7xl p-5 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
