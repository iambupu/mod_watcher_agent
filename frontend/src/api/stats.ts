import { get } from "./client";
import { nonNegativeInteger } from "./listResponse";

export interface Stats {
  total_mods: number;
  new_mods_this_week: number;
  total_favorites: number;
  total_rules: number;
  unseen_updates: number;
}

export const fetchStats = (): Promise<Stats> => get<Stats>("/jobs/stats").then((data) => ({
  total_mods: nonNegativeInteger(data?.total_mods),
  new_mods_this_week: nonNegativeInteger(data?.new_mods_this_week),
  total_favorites: nonNegativeInteger(data?.total_favorites),
  total_rules: nonNegativeInteger(data?.total_rules),
  unseen_updates: nonNegativeInteger(data?.unseen_updates),
}));
