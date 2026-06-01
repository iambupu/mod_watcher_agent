import { parseBoolean } from "./boolean";
import { parseJobMetadata } from "./jobMetadata";
import { parseWholeIntegerInput } from "./numberInput";

export type FavoriteCheckJobEntry = {
  favorite_id: number;
  title?: string | null;
  update_detected: boolean;
  last_checked_at?: string | null;
  notification_sent: boolean;
  error?: string | null;
};

export function parseFavoriteCheckEntries(metadataJson?: string | null): FavoriteCheckJobEntry[] {
  const metadata = parseJobMetadata(metadataJson);
  const results = metadata.results;
  const favorites = results && typeof results === "object" && !Array.isArray(results)
    ? (results as Record<string, unknown>).favorites
    : undefined;
  if (!Array.isArray(favorites)) return [];
  return favorites.flatMap((entry) => {
    const normalized = normalizeFavoriteCheckEntry(entry);
    return normalized ? [normalized] : [];
  });
}

function normalizeFavoriteCheckEntry(entry: unknown): FavoriteCheckJobEntry | null {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
  const raw = entry as Record<string, unknown>;
  const favoriteId = favoriteIdValue(raw.favorite_id);
  if (favoriteId <= 0) return null;
  return {
    favorite_id: favoriteId,
    title: optionalText(raw.title),
    update_detected: parseBoolean(raw.update_detected),
    last_checked_at: optionalText(raw.last_checked_at),
    notification_sent: parseBoolean(raw.notification_sent),
    error: optionalText(raw.error),
  };
}

function favoriteIdValue(value: unknown): number {
  if (typeof value !== "number" && typeof value !== "string") return 0;
  return parseWholeIntegerInput(String(value), { min: 1 }) ?? 0;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
