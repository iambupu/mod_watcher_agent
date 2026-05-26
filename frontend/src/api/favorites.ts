import { get, post, put, del } from "./client";
import { fetchMod } from "./mods";
import type { Favorite, FavoriteCheckResult, ModItem } from "@/types";
import { hydrateUpdateEvent, type BackendUpdateEvent } from "./updates";

interface BackendFavorite {
  id: number;
  mod_id: number;
  mod?: ModItem;
  tracking_enabled: boolean;
  notify_on_update: boolean;
  user_note?: string | null;
  user_tags_json: string;
  last_known_version?: string | null;
  last_known_updated_at?: string | null;
  last_checked_at?: string | null;
  translated_summary?: string | null;
}

function parseTags(value: string | undefined): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function fromBackendFavorite(raw: BackendFavorite): Favorite {
  const fallbackMod: ModItem = {
    id: raw.mod_id,
    source: "nexusmods",
    external_id: String(raw.mod_id),
    game: "",
    title: `Mod #${raw.mod_id}`,
    url: "#",
    tags_json: "[]",
    ignored: false,
    first_seen_at: "",
    last_seen_at: "",
  };
  return {
    id: raw.id,
    modId: raw.mod_id,
    mod: raw.mod
      ? { ...raw.mod, translated_summary: raw.mod.translated_summary ?? raw.translated_summary ?? undefined }
      : fallbackMod,
    trackingEnabled: raw.tracking_enabled,
    notifyOnUpdate: raw.notify_on_update,
    userNote: raw.user_note ?? undefined,
    userTags: parseTags(raw.user_tags_json),
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

export function getFavoriteModId(favorite: Favorite): number {
  return favorite.modId;
}

export const fetchFavorites = async (): Promise<Favorite[]> => {
  const raw = await get<BackendFavorite[]>("/favorites");
  return Promise.all(raw.map(hydrateFavorite));
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
    update_detected: boolean;
    update_event: BackendUpdateEvent | null;
    last_checked_at?: string | null;
    notification_sent: boolean;
  }>(`/favorites/${id}/check-update`).then((result) => ({
    favoriteId: result.favorite_id,
    modId: result.mod_id,
    updateDetected: result.update_detected,
    updateEvent: result.update_event ? hydrateUpdateEvent(result.update_event) : null,
    lastCheckedAt: result.last_checked_at ?? undefined,
    notificationSent: result.notification_sent,
  }));
