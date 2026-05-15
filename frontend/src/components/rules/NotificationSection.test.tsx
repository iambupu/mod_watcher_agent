import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotificationSection } from "./NotificationSection";
import { RuleEditorActions } from "./RuleEditorActions";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

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
    expect(screen.getByLabelText("Telegram")).toBeInTheDocument();
    expect(screen.getByLabelText("Discord")).toBeInTheDocument();
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

    const telegramCb = screen.getByLabelText("Telegram");
    const discordCb = screen.getByLabelText("Discord");

    // Initially unchecked
    expect(telegramCb).not.toBeChecked();
    expect(discordCb).not.toBeChecked();

    // Check Telegram
    await user.click(telegramCb);
    let state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["telegram"]);

    // Check Discord
    await user.click(discordCb);
    state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["telegram", "discord"]);

    // Uncheck Telegram
    await user.click(telegramCb);
    state = useRuleEditorStore.getState();
    expect(state.draft.notification.channels).toEqual(["discord"]);
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

describe("RuleEditorActions", () => {
  beforeEach(() => {
    useRuleEditorStore.setState({
      ...DEFAULT_STATE,
      isDirty: false,
      draft: { ...DEFAULT_STATE.draft, name: "" },
    });
  });

  it("renders all three buttons", () => {
    const onSave = () => {};
    const onTest = () => {};
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    expect(screen.getByText("rules.actions.saveRule")).toBeInTheDocument();
    expect(screen.getByText("rules.actions.testRule")).toBeInTheDocument();
    expect(screen.getByText("common.cancel")).toBeInTheDocument();
  });

  it("save button disabled when not dirty", () => {
    const onSave = () => {};
    const onTest = () => {};
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    const saveBtn = screen.getByText("rules.actions.saveRule");
    expect(saveBtn).toBeDisabled();
  });

  it("save button disabled when name is empty even if dirty", () => {
    useRuleEditorStore.setState({ isDirty: true, draft: { ...DEFAULT_STATE.draft, name: "" } });

    const onSave = () => {};
    const onTest = () => {};
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    const saveBtn = screen.getByText("rules.actions.saveRule");
    expect(saveBtn).toBeDisabled();
  });

  it("save button enabled when dirty and name filled", () => {
    useRuleEditorStore.setState({
      isDirty: true,
      draft: { ...DEFAULT_STATE.draft, name: "Test Rule" },
    });

    const onSave = () => {};
    const onTest = () => {};
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    const saveBtn = screen.getByText("rules.actions.saveRule");
    expect(saveBtn).not.toBeDisabled();
  });

  it("calls onCancel when cancel button clicked", async () => {
    const user = userEvent.setup();
    let called = false;
    const onSave = () => {};
    const onTest = () => {};
    const onCancel = () => { called = true; };

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    await user.click(screen.getByText("common.cancel"));
    expect(called).toBe(true);
  });

  it("calls onSave when save button clicked", async () => {
    const user = userEvent.setup();
    useRuleEditorStore.setState({
      isDirty: true,
      draft: { ...DEFAULT_STATE.draft, name: "Test Rule" },
    });

    let called = false;
    const onSave = () => { called = true; };
    const onTest = () => {};
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    await user.click(screen.getByText("rules.actions.saveRule"));
    expect(called).toBe(true);
  });

  it("calls onTest when test button clicked", async () => {
    const user = userEvent.setup();
    let called = false;
    const onSave = () => {};
    const onTest = () => { called = true; };
    const onCancel = () => {};

    render(
      <RuleEditorActions onSave={onSave} onTest={onTest} onCancel={onCancel} />
    );

    await user.click(screen.getByText("rules.actions.testRule"));
    expect(called).toBe(true);
  });
});
