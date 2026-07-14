import { describe, expect, it } from "vitest";

import {
  serializeLlmProvider,
  serializeLlmProviders,
} from "@/api/llmProviderCodec";


describe("LLM provider codec", () => {
  const provider = {
    provider: "qwen" as const,
    enabled: true,
    priority: 2,
    model: "qwen-plus",
    apiKey: "secret",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  };

  it("serializes one provider through the shared backend contract", () => {
    expect(serializeLlmProvider(provider)).toEqual({
      provider: "qwen",
      enabled: true,
      priority: 2,
      model: "qwen-plus",
      api_key: "secret",
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    });
  });

  it("serializes provider arrays without a second mapping implementation", () => {
    expect(serializeLlmProviders([provider])).toEqual([
      serializeLlmProvider(provider),
    ]);
  });
});
