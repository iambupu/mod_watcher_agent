import { describe, expect, it } from "vitest";

import { parseJsonArray, parseJsonObject, parseJsonStringArray, parseJsonText } from "./json";

describe("parseJsonStringArray", () => {
  it("returns string arrays", () => {
    expect(parseJsonStringArray('["tag","中文"]')).toEqual(["tag", "中文"]);
  });

  it("drops non-string items", () => {
    expect(parseJsonStringArray('["tag",1,null,{"bad":true}]')).toEqual(["tag"]);
  });

  it("returns an empty array for invalid or non-array JSON", () => {
    expect(parseJsonStringArray('"tag"')).toEqual([]);
    expect(parseJsonStringArray("{bad json")).toEqual([]);
    expect(parseJsonStringArray(undefined)).toEqual([]);
  });
});

describe("parseJsonText", () => {
  it("returns parsed JSON values", () => {
    expect(parseJsonText('{"ok":true}')).toEqual({ ok: true });
    expect(parseJsonText("[1,2]")).toEqual([1, 2]);
  });

  it("throws a stable message for invalid JSON", () => {
    expect(() => parseJsonText("not json")).toThrow("Invalid JSON file");
    expect(() => parseJsonText("not json", "Bad file")).toThrow("Bad file");
  });
});

describe("parseJsonArray", () => {
  it("returns arrays and rejects non-array JSON", () => {
    expect(parseJsonArray('[{"a":1}]')).toEqual([{ a: 1 }]);
    expect(parseJsonArray("{}")).toEqual([]);
    expect(parseJsonArray("{bad json")).toEqual([]);
    expect(parseJsonArray(undefined)).toEqual([]);
  });
});

describe("parseJsonObject", () => {
  it("returns plain JSON objects", () => {
    expect(parseJsonObject('{"rule_id":42,"name":"Rule"}')).toEqual({
      rule_id: 42,
      name: "Rule",
    });
  });

  it("returns an empty object for invalid or non-object JSON", () => {
    expect(parseJsonObject("[1,2]")).toEqual({});
    expect(parseJsonObject("null")).toEqual({});
    expect(parseJsonObject("{bad json")).toEqual({});
    expect(parseJsonObject(undefined)).toEqual({});
  });
});
