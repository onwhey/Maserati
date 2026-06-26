"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <Button
        type="button"
        variant="outline"
        className="fixed right-4 top-4 z-50 h-9 w-9 rounded-full border-border/70 bg-background/80 p-0 shadow-sm backdrop-blur"
        aria-label="Toggle theme"
        disabled
      >
        <Moon className="h-4 w-4 opacity-0" />
        <span className="sr-only">Toggle theme</span>
      </Button>
    );
  }

  const isDark = resolvedTheme !== "light";

  return (
    <Button
      type="button"
      variant="outline"
      className="fixed right-4 top-4 z-50 h-9 w-9 rounded-full border-border/70 bg-background/80 p-0 shadow-sm backdrop-blur hover:bg-muted"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      disabled={!mounted}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
