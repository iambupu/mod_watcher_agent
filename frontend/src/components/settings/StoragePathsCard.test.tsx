import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StoragePathsCard } from "@/components/settings/StoragePathsCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("StoragePathsCard", () => {
  it("shows the config directory and default database path and opens the directory", () => {
    const onOpenConfigDirectory = vi.fn();

    render(
      <StoragePathsCard
        runtimePaths={{
          configDir: String.raw`C:\Users\tester\AppData\Local\ModWatcherAgent\config`,
          defaultDatabasePath: String.raw`C:\Users\tester\AppData\Local\ModWatcherAgent\data\mod_watcher.db`,
          activeDatabasePath: String.raw`D:\mods\custom.db`,
        }}
        databasePath={String.raw`D:\mods\custom.db`}
        onDatabasePathChange={vi.fn()}
        onOpenConfigDirectory={onOpenConfigDirectory}
        openingConfigDirectory={false}
      />,
    );

    expect(screen.getByText(String.raw`C:\Users\tester\AppData\Local\ModWatcherAgent\config`)).toBeInTheDocument();
    expect(
      screen.getByText(String.raw`C:\Users\tester\AppData\Local\ModWatcherAgent\data\mod_watcher.db`),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue(String.raw`D:\mods\custom.db`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "settings.openConfigDirectory" }));
    expect(onOpenConfigDirectory).toHaveBeenCalledOnce();
  });
});
