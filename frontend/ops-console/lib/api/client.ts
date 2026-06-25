import { cookies, headers } from "next/headers";

import type { OpsApiResponse } from "./types";

const CONFIGURED_API_BASE = process.env.OPS_CONSOLE_API_BASE_URL ?? "";

async function buildApiUrl(path: string): Promise<string> {
  const configuredBase = CONFIGURED_API_BASE.trim().replace(/\/+$/, "");
  if (configuredBase) {
    return `${configuredBase}${path}`;
  }

  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  if (!host) {
    throw new Error("缺少请求 Host，无法构造同源 Django API 地址");
  }
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  return `${protocol}://${host}${path}`;
}

export async function opsFetch<T>(path: string): Promise<OpsApiResponse<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  let response: Response;
  try {
    response = await fetch(await buildApiUrl(path), {
      cache: "no-store",
      headers: cookieHeader ? { cookie: cookieHeader } : undefined
    });
  } catch (error) {
    return {
      ok: false,
      reason_code: "ops_console_api_unreachable",
      message_zh: error instanceof Error ? error.message : "无法访问 Django OpsConsole API",
      data: null
    };
  }

  let payload: OpsApiResponse<T>;
  try {
    payload = (await response.json()) as OpsApiResponse<T>;
  } catch {
    return {
      ok: false,
      reason_code: "ops_console_invalid_api_response",
      message_zh: `后端没有返回合法 JSON，HTTP 状态：${response.status}`,
      data: null
    };
  }
  if (!response.ok && payload.ok) {
    return {
      ok: false,
      reason_code: "ops_console_http_error",
      message_zh: `后端返回异常 HTTP 状态：${response.status}`,
      data: null
    };
  }
  return payload;
}

export async function opsPost<T>(path: string, body: Record<string, unknown>): Promise<OpsApiResponse<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const csrfToken = cookieStore.get("csrftoken")?.value;
  const requestHeaders: Record<string, string> = {
    "content-type": "application/json"
  };
  if (cookieHeader) {
    requestHeaders.cookie = cookieHeader;
  }
  if (csrfToken) {
    requestHeaders["x-csrftoken"] = csrfToken;
  }

  let response: Response;
  try {
    response = await fetch(await buildApiUrl(path), {
      method: "POST",
      cache: "no-store",
      headers: requestHeaders,
      body: JSON.stringify(body)
    });
  } catch (error) {
    return {
      ok: false,
      reason_code: "ops_console_api_unreachable",
      message_zh: error instanceof Error ? error.message : "无法访问 Django OpsConsole API",
      data: null
    };
  }

  let payload: OpsApiResponse<T>;
  try {
    payload = (await response.json()) as OpsApiResponse<T>;
  } catch {
    return {
      ok: false,
      reason_code: "ops_console_invalid_api_response",
      message_zh: `后端没有返回合法 JSON，HTTP 状态：${response.status}`,
      data: null
    };
  }
  if (!response.ok && payload.ok) {
    return {
      ok: false,
      reason_code: "ops_console_http_error",
      message_zh: `后端返回异常 HTTP 状态：${response.status}`,
      data: null
    };
  }
  return payload;
}
