import { describe, expect, it } from "vitest";

import { metadataRuleId, parseJobMetadata } from "./jobMetadata";

describe("job metadata helpers", () => {
  it("parses metadata objects and degrades invalid JSON to empty object", () => {
    expect(parseJobMetadata('{"rule_id":"42"}')).toEqual({ rule_id: "42" });
    expect(parseJobMetadata("{bad json")).toEqual({});
    expect(parseJobMetadata("[1,2]")).toEqual({});
  });

  it("extracts positive integer rule ids from number or string fields", () => {
    expect(metadataRuleId({ rule_id: 42 })).toBe(42);
    expect(metadataRuleId({ rule_id: "42" })).toBe(42);
    expect(metadataRuleId({ rule_id: "42.9" })).toBe(0);
    expect(metadataRuleId({ rule_id: "0" })).toBe(0);
    expect(metadataRuleId({ rule_id: "abc" })).toBe(0);
  });
});
