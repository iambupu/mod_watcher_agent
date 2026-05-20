import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownText } from "./MarkdownText";

describe("MarkdownText", () => {
  it("renders level-4 headings, tables, and horizontal rules", () => {
    render(
      <MarkdownText
        text={[
          "#### 收藏更新建议",
          "",
          "类别 | 示例模组 |",
          "------|------|",
          "角色与外观 | **H.O.A.** |",
          "BUG修复 | `Crossbow Reload` |",
          "---",
          "- 后续建议",
          "普通段落",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { name: "收藏更新建议", level: 6 })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "类别" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "示例模组" })).toBeInTheDocument();
    expect(within(table).getByText("H.O.A.")).toBeInTheDocument();
    expect(within(table).getByText("Crossbow Reload")).toBeInTheDocument();
    expect(document.querySelector("hr")).toBeInTheDocument();
    expect(screen.getByText("后续建议")).toBeInTheDocument();
    expect(screen.getByText("普通段落")).toBeInTheDocument();
  });
});
