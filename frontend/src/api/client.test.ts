import { afterEach, describe, expect, it, vi } from "vitest";

import { clearSecurityToken, get, post, setSecurityToken } from "./client";


describe("api client security token", () => {
  afterEach(() => {
    clearSecurityToken();
    vi.restoreAllMocks();
  });

  it("adds X-Mod-Watcher-Token header when token is configured", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as Response);

    setSecurityToken("token-123");
    await get<{ ok: boolean }>("/settings");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Mod-Watcher-Token"]).toBe("token-123");
  });

  it("does not add token header when token is empty", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as Response);

    clearSecurityToken();
    await get<{ ok: boolean }>("/settings");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Mod-Watcher-Token"]).toBeUndefined();
  });

  it("serializes falsy request bodies", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    } as Response);

    await post<{ ok: boolean }>("/test", false);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe("false");
  });
});
