"use server";

import { redirect } from "next/navigation";

import { opsLogout } from "@/lib/api/client";

export async function logoutAction(): Promise<void> {
  await opsLogout();
  redirect("/login");
}
