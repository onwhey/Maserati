import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/ops/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Cypto OpsConsole",
  description: "OpsConsole"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
