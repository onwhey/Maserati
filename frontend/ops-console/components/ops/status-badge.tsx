import { Badge } from "@/components/ui/badge";

function toneFor(value: unknown) {
  const text = String(value ?? "").toLowerCase();
  if (["succeeded", "completed", "allow", "allowed", "calculated", "sent", "filled", "true", "ok"].some((item) => text.includes(item))) {
    return "green" as const;
  }
  if (["blocked", "unknown", "warning", "pending", "waiting", "open"].some((item) => text.includes(item))) {
    return "amber" as const;
  }
  if (["failed", "denied", "rejected", "error", "critical", "false"].some((item) => text.includes(item))) {
    return "red" as const;
  }
  return "muted" as const;
}

export function StatusBadge({ value }: { value: unknown }) {
  return <Badge tone={toneFor(value)}>{String(value ?? "—")}</Badge>;
}
