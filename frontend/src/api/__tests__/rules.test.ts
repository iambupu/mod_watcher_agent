// 中文注释：封装前端访问后端rules.test接口的类型和请求函数。

import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "@/api/client";
import { fetchRules, importRulesFromLocalFile } from "@/api/rules";

vi.mock("@/api/client", () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const fileWithText = (text: string): File => ({ text: async () => text }) as File;

describe("rules API import", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("rejects invalid local JSON before posting", async () => {
    await expect(importRulesFromLocalFile(fileWithText("not json"))).rejects.toThrow("Invalid JSON file");

    expect(post).not.toHaveBeenCalled();
  });

  it("rejects local JSON without a rules array before posting", async () => {
    await expect(importRulesFromLocalFile(fileWithText('{"rules":{}}'))).rejects.toThrow(
      "JSON must be an array or an object with 'rules' array",
    );

    expect(post).not.toHaveBeenCalled();
  });

  it("posts rules from either array or export-object files", async () => {
    vi.mocked(post).mockResolvedValue({ imported: 1, skipped: 0 });
    const rules = [{ name: "Rule A" }];

    await expect(importRulesFromLocalFile(fileWithText(JSON.stringify(rules)))).resolves.toEqual({
      imported: 1,
      skipped: 0,
    });
    await importRulesFromLocalFile(fileWithText(JSON.stringify({ version: 1, rules })));

    expect(post).toHaveBeenNthCalledWith(1, "/rules/import", { rules });
    expect(post).toHaveBeenNthCalledWith(2, "/rules/import", { rules });
  });

  it("normalizes boolean-like enabled values from backend payloads", async () => {
    vi.mocked(get).mockResolvedValue([
      {
        id: 1,
        name: "Rule A",
        enabled: "false",
        intervalMinutes: 30,
        source: "nexusmods",
        sourceConfig: {},
        filters: {},
        notification: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);

    await expect(fetchRules()).resolves.toMatchObject([{ enabled: false }]);
  });

  it("treats malformed rule list responses as empty", async () => {
    vi.mocked(get).mockResolvedValue({ items: [] });

    await expect(fetchRules()).resolves.toEqual([]);
  });
});
