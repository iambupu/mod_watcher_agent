import { get } from "./client";

interface ModSummary {
  id: number;
  mod_id: number;
  language: string;
  summary_type: string;
  content: string;
  model?: string;
  generated_at: string;
}

export const fetchSummary = (modId: number, language: string = "zh-CN") =>
  get<ModSummary>(`/mods/${modId}/summary?language=${language}`);
