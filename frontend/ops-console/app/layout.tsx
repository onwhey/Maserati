import type { Metadata } from "next";
import type { ReactNode } from "react";

import { logoutAction } from "@/app/logout/actions";
import { AppShell } from "@/components/ops/app-shell";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Cypto OpsConsole",
  description: "OpsConsole"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          disableTransitionOnChange
          enableSystem={false}
          storageKey="ops-console-theme"
        >
          <ThemeToggle />
          <AppShell logoutAction={logoutAction}>{children}</AppShell>
        </ThemeProvider>
      </body>
    </html>
  );
}
