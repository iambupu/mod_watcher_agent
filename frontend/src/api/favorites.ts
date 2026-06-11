// 中文注释：封装前端访问后端收藏接口的类型和请求函数。

import { get, post, put, del } from "./client";
import { fetchMod } from "./mods";
import { fallbackModItem, mergeTranslatedSummary } from "./modHydration";
import type { Favorite, FavoriteCheckResult, ModItem } from "@/types";
import { hydrateUpdateEvent, type BackendUpdateEvent } from "./updates";
import { arrayOrEmpty } from "@/utils/array";
import { parseJsonStringArray } from "@/utils/json";
import { parseBoolean } from "@/utils/boolean";

export type FavoriteRef = Pick<Favorite, "id" | "modId">;

interface BackendFavorite {
  id: number;
  mod_id: number;
  mod?: ModItem;
  tracking_enabled: unknown;
  notify_on_update: unknown;
  user_note?: string | null;
  user_tags_json: string;
  last_known_version?: string | null;
  last_known_updated_at?: string | null;
  last_checked_at?: string | null;
  translated_summary?: string | null;
}

function fromBackendFavorite(raw: BackendFavorite): Favorite {
  return {
    id: raw.id,
    modId: raw.mod_id,
    mod: raw.mod
      ? mergeTranslatedSummary(raw.mod, raw.translated_summary)
      : fallbackModItem(raw.mod_id, { url: "#", translatedSummary: raw.translated_summary }),
    trackingEnabled: parseBoolean(raw.tracking_enabled),
    notifyOnUpdate: parseBoolean(raw.notify_on_update),
    userNote: raw.user_note ?? undefined,
    userTags: parseJsonStringArray(raw.user_tags_json),
    lastKnownVersion: raw.last_known_version ?? undefined,
    lastKnownUpdatedAt: raw.last_known_updated_at ?? undefined,
    lastCheckedAt: raw.last_checked_at ?? undefined,
  };
}

async function hydrateFavorite(raw: BackendFavorite): Promise<Favorite> {
  if (raw.mod) {
    return fromBackendFavorite(raw);
  }
  try {
    const mod = await fetchMod(raw.mod_id);
    return fromBackendFavorite({ ...raw, mod });
  } catch {
    return fromBackendFavorite(raw);
  }
}

function toBackendFavoriteUpdate(data: Partial<Favorite>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (data.trackingEnabled !== undefined) payload.tracking_enabled = data.trackingEnabled;
  if (data.notifyOnUpdate !== undefined) payload.notify_on_update = data.notifyOnUpdate;
  if (data.userNote !== undefined) payload.user_note = data.userNote;
  if (data.userTags !== undefined) payload.user_tags_json = JSON.stringify(data.userTags);
  return payload;
}

export function getFavoriteModId(favorite: Pick<Favorite, "modId">): number {
  return favorite.modId;
}

export function favoriteByModId<T extends FavoriteRef>(favorites: T[] | undefined): Map<number, T> {
  const pairs = new Map<number, T>();
  for (const favorite of favorites ?? []) {
    pairs.set(getFavoriteModId(favorite), favorite);
  }
  return pairs;
}

export function favoriteIdByModId(favorites: FavoriteRef[] | undefined): Map<number, number> {
  const pairs = new Map<number, number>();
  for (const favorite of favorites ?? []) {
    pairs.set(getFavoriteModId(favorite), favorite.id);
  }
  return pairs;
}

export const fetchFavorites = async (): Promise<Favorite[]> => {
  const raw = await get<BackendFavorite[]>("/favorites");
  return Promise.all(arrayOrEmpty<BackendFavorite>(raw).map(hydrateFavorite));
};

export const fetchFavoriteRefs = async (): Promise<FavoriteRef[]> => {
  const raw = await get<BackendFavorite[]>("/favorites", { detail: "refs" });
  return arrayOrEmpty<BackendFavorite>(raw).map((favorite) => ({
    id: favorite.id,
    modId: favorite.mod_id,
  }));
};

export const addFavorite = async (data: {
  mod_id: number;
  tracking_enabled?: boolean;
  notify_on_update?: boolean;
  user_note?: string;
}): Promise<Favorite> => hydrateFavorite(await post<BackendFavorite>("/favorites", data));

export const updateFavorite = (id: number, data: Partial<Favorite>): Promise<Favorite> =>
  put<BackendFavorite>(`/favorites/${id}`, toBackendFavoriteUpdate(data)).then(hydrateFavorite);

export const removeFavorite = (id: number): Promise<void> => del(`/favorites/${id}`);

export const checkUpdate = (
  id: number,
): Promise<FavoriteCheckResult> =>
  post<{
    favorite_id: number;
    mod_id: number;
    update_detected: unknown;
    update_event: BackendUpdateEvent | null;
    last_checked_at?: string | null;
    notification_sent: unknown;
  }>(`/favorites/${id}/check-update`).then((result) => ({
    favoriteId: result.favorite_id,
    modId: result.mod_id,
    updateDetected: parseBoolean(result.update_detected),
    updateEvent: result.update_event ? hydrateUpdateEvent(result.update_event) : null,
    lastCheckedAt: result.last_checked_at ?? undefined,
    notificationSent: parseBoolean(result.notification_sent),
  }));
