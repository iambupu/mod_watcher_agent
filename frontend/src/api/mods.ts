import { get, post } from "./client";
import type { ModItem, ModList } from "@/types";

export interface ModsQueryParams {
  game?: string;
  source?: string;
  contentLanguage?: string;
  search?: string;
  adultContent?: "include" | "exclude" | "only";
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  offset?: number;
  limit?: number;
}

export interface ModGameOption {
  value: string;
  label: string;
  count: number;
}

function buildModsQuery(params: ModsQueryParams): Record<string, string> {
  const query: Record<string, string> = {};
  if (params.game) query.game = params.game;
  if (params.source) query.source = params.source;
  if (params.contentLanguage) query.content_language = params.contentLanguage;
  if (params.search) query.search = params.search;
  if (params.adultContent) query.adult_content = params.adultContent;
  if (params.sortBy) query.sort_by = params.sortBy;
  if (params.sortOrder) query.sort_order = params.sortOrder;
  if (params.offset !== undefined) query.offset = String(params.offset);
  if (params.limit !== undefined) query.limit = String(params.limit);
  return query;
}

export async function fetchMods(params: ModsQueryParams): Promise<ModList> {
  const query = buildModsQuery(params);
  return get<ModList>("/mods", query);
}

export async function fetchIgnoredMods(params: ModsQueryParams = {}): Promise<ModList> {
  const query = buildModsQuery(params);
  return get<ModList>("/mods/ignored", query);
}

export async function fetchRecommendedMods(limit = 5): Promise<ModList> {
  return get<ModList>("/mods/recommendations", { limit: String(limit) });
}

export async function fetchModGames(): Promise<ModGameOption[]> {
  return get<ModGameOption[]>("/mods/games");
}

export async function fetchMod(id: number): Promise<ModItem> {
  return get<ModItem>(`/mods/${id}`);
}

export async function ignoreMod(id: number): Promise<{ ignored: boolean }> {
  return post<{ ignored: boolean }>(`/mods/${id}/ignore`);
}

export async function unignoreMod(id: number): Promise<{ ignored: boolean }> {
  return post<{ ignored: boolean }>(`/mods/${id}/unignore`);
}

export async function regenerateModSummary(id: number): Promise<{ status: string; mod_id: number; language: string }> {
  return post<{ status: string; mod_id: number; language: string }>(`/mods/${id}/summary/regenerate`);
}

export async function generateModIntroduction(id: number): Promise<{ status: string; mod_id: number; language: string; content: string }> {
  return post<{ status: string; mod_id: number; language: string; content: string }>(`/mods/${id}/introduction/generate`);
}
