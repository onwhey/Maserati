import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import type { OpsApiResponse } from "./types";

const CONFIGURED_API_BASE = process.env.OPS_CONSOLE_API_BASE_URL ?? "";
const LOGIN_REQUIRED_REASON = "ops_console_login_required";
const SESSION_COOKIE_NAME = "sessionid";
const CSRF_COOKIE_NAME = "csrftoken";

export async function buildApiUrl(path: string): Promise<string> {
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

function redirectToLogin(): never {
  redirect("/login");
}

export async function opsFetch<T>(path: string): Promise<OpsApiResponse<T>> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const apiUrl = await buildApiUrl(path);
  let response: Response;
  try {
    response = await fetch(apiUrl, {
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
  if (payload.reason_code === LOGIN_REQUIRED_REASON) {
    redirectToLogin();
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

  const apiUrl = await buildApiUrl(path);
  let response: Response;
  try {
    response = await fetch(apiUrl, {
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
  if (payload.reason_code === LOGIN_REQUIRED_REASON) {
    redirectToLogin();
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

export async function opsLogin(username: string, password: string): Promise<OpsApiResponse<Record<string, unknown>>> {
  const response = await fetch(await buildApiUrl("/api/ops/auth/login/"), {
    method: "POST",
    cache: "no-store",
    headers: {
      "content-type": "application/json"
    },
    body: JSON.stringify({ username, password })
  });
  const payload = (await response.json()) as OpsApiResponse<Record<string, unknown>>;
  if (payload.ok) {
    const setCookieHeader = response.headers.get("set-cookie");
    const sessionValue = extractCookieValue(setCookieHeader, SESSION_COOKIE_NAME);
    const csrfValue = extractCookieValue(setCookieHeader, CSRF_COOKIE_NAME);
    if (sessionValue) {
      const cookieStore = await cookies();
      cookieStore.set(SESSION_COOKIE_NAME, sessionValue, {
        httpOnly: true,
        sameSite: "lax",
        path: "/"
      });
      if (csrfValue) {
        cookieStore.set(CSRF_COOKIE_NAME, csrfValue, {
          httpOnly: false,
          sameSite: "lax",
          path: "/"
        });
      }
    }
  }
  return payload;
}

export async function opsLogout(): Promise<OpsApiResponse<Record<string, unknown>>> {
  const cookieStore = await cookies();
  try {
    return await opsPost<Record<string, unknown>>("/api/ops/auth/logout/", {});
  } finally {
    cookieStore.delete(SESSION_COOKIE_NAME);
    cookieStore.delete(CSRF_COOKIE_NAME);
  }
}

function extractCookieValue(setCookieHeader: string | null, cookieName: string): string {
  if (!setCookieHeader) {
    return "";
  }
  const match = setCookieHeader.match(new RegExp(`(?:^|,\\s*)${cookieName}=([^;]+)`));
  return match?.[1] ?? "";
}
