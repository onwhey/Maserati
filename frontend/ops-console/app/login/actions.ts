"use server";

import { redirect } from "next/navigation";

import { opsLogin } from "@/lib/api/client";

export async function loginAction(formData: FormData): Promise<void> {
  const username = String(formData.get("username") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = safeNextPath(String(formData.get("next") ?? "/"));

  const result = await opsLogin(username, password);
  if (result.ok) {
    redirect(next);
  }

  const reason = encodeURIComponent(result.reason_code);
  const message = encodeURIComponent(result.message_zh);
  redirect(`/login?next=${encodeURIComponent(next)}&reason=${reason}&message=${message}`);
}

function safeNextPath(value: string): string {
  if (!value.startsWith("/") || value.startsWith("//")) {
    return "/";
  }
  return value;
}
