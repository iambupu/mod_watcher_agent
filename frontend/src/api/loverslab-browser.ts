// 中文注释：封装前端访问后端LoversLab 浏览器辅助接口的类型和请求函数。

import { get, post } from "./client";

type LoversLabBrowserStatusValue =
  | "ok"
  | "login_required"
  | "cloudflare_challenge"
  | "forbidden"
  | "timeout"
  | "playwright_not_installed"
  | "browser_not_installed"
  | "structure_changed"
  | "unknown_error";

export interface LoversLabBrowserStatus {
  profileExists: boolean;
  playwrightInstalled: boolean;
  browserInstalled: boolean;
  browserName?: string;
  browserSource?: "playwright" | "system" | "";
  browserChannel?: string;
  lastCheckStatus: LoversLabBrowserStatusValue | null;
  lastCheckAt: string | null;
  error?: string;
}

export interface LoversLabSessionResult {
  status: LoversLabBrowserStatusValue;
  url: string;
  finalUrl: string;
  title: string;
  checkedAt?: string;
  error?: string | null;
}

interface LoversLabCategoryItem {
  fileId: string;
  title: string;
  url: string;
  author: string;
  updatedAt: string | null;
  thumbnailUrl: string;
  summary: string;
  contentHash: string;
}

export interface LoversLabCategoryTestResult {
  status: LoversLabBrowserStatusValue;
  title: string;
  finalUrl: string;
  itemsCount: number;
  items: LoversLabCategoryItem[];
  error?: string | null;
}

export interface LoversLabSnapshotResult {
  status: LoversLabBrowserStatusValue;
  path: string;
  title: string;
  finalUrl: string;
}

export interface LoversLabInstallResult {
  success: boolean;
  status: LoversLabBrowserStatusValue;
  message: string;
  stdout: string;
  stderr: string;
}

export function fetchLoversLabBrowserStatus(): Promise<LoversLabBrowserStatus> {
  return get<LoversLabBrowserStatus>("/loverslab/browser/status");
}

export function openLoversLabLogin(): Promise<LoversLabSessionResult> {
  return post<LoversLabSessionResult>("/loverslab/browser/open-login");
}

export function checkLoversLabSession(): Promise<LoversLabSessionResult> {
  return post<LoversLabSessionResult>("/loverslab/browser/check-session");
}

export function installLoversLabChromium(): Promise<LoversLabInstallResult> {
  return post<LoversLabInstallResult>("/loverslab/browser/install-chromium");
}

export function testLoversLabCategory(payload: {
  url: string;
  gameLabel: string;
  maxItems: number;
}): Promise<LoversLabCategoryTestResult> {
  return post<LoversLabCategoryTestResult>("/loverslab/browser/test-category", payload);
}

export function saveLoversLabSnapshot(payload: {
  url: string;
  profileName?: string;
}): Promise<LoversLabSnapshotResult> {
  return post<LoversLabSnapshotResult>("/loverslab/browser/save-snapshot", payload);
}
