import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/settings", () => ({
  fetchSettings: vi.fn(),
}));

vi.mock("@/api/system-notifications", () => ({
  dispatchWindowsNotifications: vi.fn(),
  fetchRecentNotifications: vi.fn(),
  markNotificationsSeen: vi.fn(),
}));

describe("useSystemNotifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not dispatch notifications after unmount during polling", async () => {
    const { fetchSettings } = await import("@/api/settings");
    const { dispatchWindowsNotifications, fetchRecentNotifications, markNotificationsSeen } = await import(
      "@/api/system-notifications"
    );
    let resolveSettings: (value: unknown) => void = () => {};
    (fetchSettings as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((resolve) => {
        resolveSettings = resolve;
      }),
    );
    (fetchRecentNotifications as ReturnType<typeof vi.fn>).mockResolvedValue([{ id: 1, title: "t" }]);
    (dispatchWindowsNotifications as ReturnType<typeof vi.fn>).mockResolvedValue([1]);

    const { useSystemNotifications } = await import("@/hooks/useSystemNotifications");
    const { unmount } = renderHook(() => useSystemNotifications());

    await waitFor(() => {
      expect(fetchSettings).toHaveBeenCalledTimes(1);
    });
    unmount();
    resolveSettings({ notificationsEnabled: true, systemNotificationsEnabled: true });
    await Promise.resolve();

    expect(fetchRecentNotifications).not.toHaveBeenCalled();
    expect(dispatchWindowsNotifications).not.toHaveBeenCalled();
    expect(markNotificationsSeen).not.toHaveBeenCalled();
  });

  it("does not start overlapping polls while a previous poll is running", async () => {
    vi.useFakeTimers();
    const { fetchSettings } = await import("@/api/settings");
    let resolveSettings: (value: unknown) => void = () => {};
    (fetchSettings as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((resolve) => {
        resolveSettings = resolve;
      }),
    );

    const { useSystemNotifications } = await import("@/hooks/useSystemNotifications");
    const { unmount } = renderHook(() => useSystemNotifications());

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30_000);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(fetchSettings).toHaveBeenCalledTimes(1);

    resolveSettings({ notificationsEnabled: false, systemNotificationsEnabled: false });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(30_000);

    expect(fetchSettings).toHaveBeenCalledTimes(2);
    unmount();
  });
});
