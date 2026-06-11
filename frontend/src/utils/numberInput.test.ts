// 中文注释：提供 numberInput.test 相关的前端纯函数工具。

import { describe, expect, it } from "vitest";

import {
  clampIntegerInput,
  clampNumberInput,
  nonNegativeNumberValue,
  numberValue,
  parseIntegerInput,
  parseWholeIntegerInput,
} from "./numberInput";

describe("number input helpers", () => {
  it("parses bounded integer input for rule forms", () => {
    expect(parseIntegerInput("12.9", { min: 1, max: 20 })).toBe(12);
    expect(parseIntegerInput("99", { min: 1, max: 20 })).toBe(20);
    expect(parseIntegerInput("0", { min: 1, max: 20 })).toBeNull();
    expect(parseIntegerInput("", { allowEmpty: true })).toBeUndefined();
  });

  it("clamps settings input with a fallback for invalid values", () => {
    expect(clampIntegerInput("12.9", { min: 1, max: 20, fallback: 5 })).toBe(12);
    expect(clampIntegerInput("99", { min: 1, max: 20, fallback: 5 })).toBe(20);
    expect(clampIntegerInput("-2", { min: 1, max: 20, fallback: 5 })).toBe(1);
    expect(clampIntegerInput("", { min: 1, max: 20, fallback: 5 })).toBe(5);
  });

  it("clamps decimal input with a fallback for invalid values", () => {
    expect(clampNumberInput("0.75", { min: 0, max: 1, fallback: 0.5 })).toBe(0.75);
    expect(clampNumberInput("2", { min: 0, max: 1, fallback: 0.5 })).toBe(1);
    expect(clampNumberInput("-1", { min: 0, max: 1, fallback: 0.5 })).toBe(0);
    expect(clampNumberInput("bad", { min: 0, max: 1, fallback: 0.5 })).toBe(0.5);
  });

  it("parses only whole integers when decimals must be rejected", () => {
    expect(parseWholeIntegerInput("42", { min: 1 })).toBe(42);
    expect(parseWholeIntegerInput("42.9", { min: 1 })).toBeNull();
    expect(parseWholeIntegerInput("0", { min: 1 })).toBeNull();
    expect(parseWholeIntegerInput("", { allowEmpty: true })).toBeUndefined();
  });

  it("normalizes runtime numeric values from API/cache payloads", () => {
    expect(numberValue(42)).toBe(42);
    expect(numberValue("42")).toBe(42);
    expect(numberValue(" 42.5 ")).toBe(42.5);
    expect(numberValue("")).toBeNull();
    expect(numberValue("bad")).toBeNull();
    expect(numberValue(Number.NaN)).toBeNull();
  });

  it("rejects negative runtime metrics", () => {
    expect(nonNegativeNumberValue("12")).toBe(12);
    expect(nonNegativeNumberValue(0)).toBe(0);
    expect(nonNegativeNumberValue("-1")).toBeNull();
  });
});
