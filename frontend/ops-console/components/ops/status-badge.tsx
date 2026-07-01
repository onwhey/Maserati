import { Badge } from "@/components/ui/badge";

const statusLabelMap: Record<string, string> = {
  draft: "草稿",
  validating: "验证中",
  approved: "已批准",
  rejected: "已拒绝",
  invalidated: "已失效",
  active: "可用",
  deprecated: "已弃用",
  retired: "已退役",
  disabled: "已禁用",
  queued: "排队中",
  running: "运行中",
  running_completed_without_result: "疑似卡住",
  running_progress_stale: "疑似卡住",
  succeeded: "已完成",
  blocked: "已阻断",
  failed: "失败",
  true: "是",
  false: "否"
};

function toneFor(value: unknown) {
  const text = String(value ?? "").toLowerCase();
  if (["blocked", "unknown", "warning", "pending", "waiting", "open", "queued", "running", "stale"].some((item) => text.includes(item))) {
    return "amber" as const;
  }
  if (["succeeded", "completed", "allow", "allowed", "calculated", "sent", "filled", "true", "ok"].some((item) => text.includes(item))) {
    return "green" as const;
  }
  if (["failed", "denied", "rejected", "error", "critical", "false"].some((item) => text.includes(item))) {
    return "red" as const;
  }
  return "muted" as const;
}

export function StatusBadge({ value }: { value: unknown }) {
  const rawValue = String(value ?? "");
  const displayValue = (statusLabelMap[rawValue.toLowerCase()] ?? rawValue) || "—";
  return <Badge tone={toneFor(value)}>{displayValue}</Badge>;
}
