// 中文注释：封装前端访问后端stats.test接口的类型和请求函数。

import { beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "@/api/client";
import { fetchStats } from "@/api/stats";

vi.mock("@/api/client", () => ({
  get: vi.fn(),
}));

describe("stats API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes dirty numeric stats fields", async () => {
    vi.mocked(get).mockResolvedValue({
      total_mods: "3.9",
      new_mods_this_week: -1,
      total_favorites: "bad",
      total_rules: 2,
      unseen_updates: null,
    });

    await expect(fetchStats()).resolves.toEqual({
      total_mods: 3,
      new_mods_this_week: 0,
      total_favorites: 0,
      total_rules: 2,
      unseen_updates: 0,
    });
  });

  it("treats empty stats responses as zero counts", async () => {
    vi.mocked(get).mockResolvedValue(null);

    await expect(fetchStats()).resolves.toEqual({
      total_mods: 0,
      new_mods_this_week: 0,
      total_favorites: 0,
      total_rules: 0,
      unseen_updates: 0,
    });
  });
});
