import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotificationSection } from "./NotificationSection";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const DEFAULT_STATE = {
  draft: {
    name: "",
    enabled: true,
    intervalMinutes: 360,
    commonFilters: {},
    nexusmodsDraft: {
      gameDomainName: "",
      updatedSinceDays: 7,
    },
    loverslabDraft: {
      gameLabel: "",
    },
    notification: {
      enabled: true,
      mode: "instant" as const,
    },
  },
  activeSource: "nexusmods" as const,
  isDirty: false,
  editingRuleId: null as number | null,
};

describe("NotificationSection", () => {
  beforeEach(() => {
    useRuleEditorStore.setState(DEFAULT_STATE);
  });

  it("renders enabled switch", () => {
    render(<NotificationSection />);
    const switchEl = screen.getByRole("switch");
    expect(switchEl).toBeInTheDocument();
    expect(switchEl).toHaveAttribute("aria-checked", "true");
  });

  it("shows mode select and channels when enabled", () => {
    render(<NotificationSection />);
    expect(screen.getByText("rules.notification.mode")).toBeInTheDocument();
    expect(screen.getByText("rules.notification.channels")).toBeInTheDocument();
    expect(screen.getByLabelText("rules.notification.channelDesktop")).toBeInTheDocument();
    expect(screen.getByLabelText("rules.notification.channelTelegram")).toBeInTheDocument();
    expect(screen.getByLabelText("rules.notification.channelDiscord")).toBeInTheDocument();
  });

  it("hides mode and channels when notification disabled", async () => {
    const user = userEvent.setup();
    render(<NotificationSection />);

    const switchEl = screen.getByRole("switch");
    await user.click(switchEl);

    expect(screen.queryByText("rules.notification.mode")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.notification.channels")).not.toBeInTheDocument();
  });

  it("changes mode via select", async () => {
    const user = userEvent.setup();
    render(<NotificationSection />);

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "daily_digest");

    const state = useRuleEditorStore.getState();
    expect(state.draft.notification.mode).toBe("daily_digest");
    expect(state.isDirty).toBe(true);
  });

  it("toggles channels via checkboxes", async () => {
    const user = userEvent.setup();
    render(<NotificationSection />);

    const desktopCb = screen.getByLabelText("rules.notification.channelDesktop");
    const telegramCb = screen.getByLabelText("rules.notification.channelTelegram");
    const discordCb = screen.getByLabelText("rules.notification.channelDiscord");

    // Initially unchecked
    expect(desktopCb).not.toBeChecked();
    expect(telegramCb).not.toBeChecked();
    expect(discordCb).not.toBeChecked();

    // Check system notifications
    await user.click(desktopCb);
    let state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["desktop"]);

    // Check Telegram
    await user.click(telegramCb);
    state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["desktop", "telegram"]);

    // Check Discord
    await user.click(discordCb);
    state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["desktop", "telegram", "discord"]);

    // Uncheck Telegram
    await user.click(telegramCb);
    state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["desktop", "discord"]);
  });

  it("reads notification config from store", () => {
    useRuleEditorStore.setState({
      draft: {
        ...useRuleEditorStore.getState().draft,
        notification: {
          enabled: false,
          mode: "weekly_digest",
          channels: ["telegram", "discord"],
        },
      },
    });

    render(<NotificationSection />);

    const switchEl = screen.getByRole("switch");
    expect(switchEl).toHaveAttribute("aria-checked", "false");
    // Mode/channels hidden when disabled
    expect(screen.queryByText("rules.notification.mode")).not.toBeInTheDocument();
  });
});
