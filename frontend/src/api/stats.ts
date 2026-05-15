import { get } from "./client";

export interface Stats {
  total_mods: number;
  new_mods_this_week: number;
  total_favorites: number;
  total_rules: number;
  unseen_updates: number;
}

export const fetchStats = (): Promise<Stats> => get<Stats>("/jobs/stats");
