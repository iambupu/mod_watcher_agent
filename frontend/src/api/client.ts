const BASE_URL = "/api";
const SECURITY_TOKEN_STORAGE_KEY = "mw_security_token";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}
export function getSecurityToken(): string {
  return localStorage.getItem(SECURITY_TOKEN_STORAGE_KEY) || "";
}

export function setSecurityToken(token: string): void {
  const value = token.trim();
  if (!value) {
    localStorage.removeItem(SECURITY_TOKEN_STORAGE_KEY);
    return;
  }
  localStorage.setItem(SECURITY_TOKEN_STORAGE_KEY, value);
}

export function clearSecurityToken(): void {
  localStorage.removeItem(SECURITY_TOKEN_STORAGE_KEY);
}

export function buildApiUrl(endpoint: string): string {
  return new URL(`${BASE_URL}${endpoint}`, window.location.origin).toString();
}

export function buildAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getSecurityToken();
  if (token) {
    headers["X-Mod-Watcher-Token"] = token;
  }
  return headers;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string>;
}

async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params } = options;

  const url = new URL(buildApiUrl(endpoint));
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      url.searchParams.append(key, value);
    });
  }

  const headers: Record<string, string> = buildAuthHeaders({
    "Content-Type": "application/json",
  });

  const res = await fetch(url.toString(), {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });

  if (!res.ok) {
    let detail: unknown = "";
    try {
      const errorBody = await res.json();
      detail = errorBody.detail ?? errorBody.message ?? "";
    } catch {
      // Response body is not JSON or is empty
    }
    const detailText = typeof detail === "string" ? detail : JSON.stringify(detail);
    const message = detailText
      ? `API Error ${res.status}: ${detailText}`
      : `API Error: ${res.status} ${res.statusText}`;
    throw new ApiError(message, res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

export async function get<T>(endpoint: string, params?: Record<string, string>): Promise<T> {
  return request<T>(endpoint, { params });
}

export async function post<T>(endpoint: string, body?: unknown): Promise<T> {
  return request<T>(endpoint, { method: "POST", body });
}

export async function put<T>(endpoint: string, body?: unknown): Promise<T> {
  return request<T>(endpoint, { method: "PUT", body });
}

export async function patch<T>(endpoint: string, body?: unknown): Promise<T> {
  return request<T>(endpoint, { method: "PATCH", body });
}

export async function del<T>(endpoint: string): Promise<T> {
  return request<T>(endpoint, { method: "DELETE" });
}

// ── Token → httpOnly cookie migration ────────────────────────────

export async function migrateTokenToCookie(): Promise<boolean> {
  const token = getSecurityToken();
  if (!token) {
    return false;
  }
  try {
    const url = buildApiUrl("/auth/login");
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Mod-Watcher-Token": token,
      },
      body: JSON.stringify({ token }),
    });
    if (res.ok) {
      clearSecurityToken();
      return true;
    }
    // Login failed (possibly stale token). Check if cookie auth is
    // already valid — if so, the localStorage token is safe to clear.
    const statusRes = await fetch(buildApiUrl("/auth/status"), {
      credentials: "include",
    });
    if (statusRes.ok) {
      const body = await statusRes.json();
      if (body.authenticated === true) {
        clearSecurityToken();
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}
