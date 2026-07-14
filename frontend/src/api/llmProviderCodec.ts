import { DEFAULT_PROVIDER_BASE_URLS, KNOWN_LLM_PROVIDERS } from "@/constants/llmProviders";
import type { LlmProvider, LlmProviderConfig } from "@/types";
import { parseBoolean } from "@/utils/boolean";
import { parseJsonArray } from "@/utils/json";
import { clampIntegerInput } from "@/utils/numberInput";

export interface BackendLlmProviderConfig {
  provider: string;
  enabled: boolean;
  priority: number;
  model: string;
  api_key: string;
  base_url: string;
}

interface LegacyLlmProviderConfig {
  provider: string;
  model: string;
  apiKey: string;
  baseUrl: string;
}

export function isKnownLlmProvider(provider: string): provider is LlmProvider {
  return KNOWN_LLM_PROVIDERS.has(provider as LlmProvider);
}

export function parseLlmProviders(
  rawJson: string | undefined,
  legacy: LegacyLlmProviderConfig,
): LlmProviderConfig[] {
  const providers = parseJsonArray(rawJson).flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Partial<BackendLlmProviderConfig>;
    const provider = raw.provider || "";
    if (!isKnownLlmProvider(provider)) return [];
    return [{
      provider,
      enabled: parseBoolean(raw.enabled),
      priority: clampIntegerInput(String(raw.priority ?? ""), {
        min: 1,
        max: 999,
        fallback: 999,
      }),
      model: raw.model || "",
      apiKey: raw.api_key || "",
      baseUrl: raw.base_url || DEFAULT_PROVIDER_BASE_URLS[provider] || "",
    }];
  });
  if (providers.length > 0) return providers;
  const provider = isKnownLlmProvider(legacy.provider) ? legacy.provider : "openai";
  return [{
    provider,
    enabled: true,
    priority: 1,
    model: legacy.model,
    apiKey: legacy.apiKey,
    baseUrl: legacy.baseUrl || DEFAULT_PROVIDER_BASE_URLS[provider],
  }];
}

export function serializeLlmProvider(
  provider: LlmProviderConfig,
): BackendLlmProviderConfig {
  return {
    provider: provider.provider,
    enabled: provider.enabled,
    priority: provider.priority,
    model: provider.model,
    api_key: provider.apiKey,
    base_url: provider.baseUrl,
  };
}

export function serializeLlmProviders(
  providers: LlmProviderConfig[],
): BackendLlmProviderConfig[] {
  return providers.map(serializeLlmProvider);
}
