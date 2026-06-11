import type { AgentResponseCards as ApiAgentResponseCards } from "@/api/agent";
import type { ApiResponseCards, AssistantSections, ChatResponseCards } from "./types";

export const toChatResponseCards = (cards?: ApiAgentResponseCards): ChatResponseCards | undefined => {
  if (!cards) return undefined;
  return {
    analysis: cards.analysis,
    evidence: cards.evidence,
    conclusion: cards.conclusion,
    understanding: cards.understanding,
    filters: cards.filters,
    results: cards.results,
    nextSteps: cards.next_steps,
  };
};

export const toApiResponseCards = (cards?: ChatResponseCards): ApiResponseCards | undefined => {
  if (!cards) return undefined;
  return {
    analysis: cards.analysis,
    evidence: cards.evidence,
    conclusion: cards.conclusion,
    understanding: cards.understanding,
    filters: cards.filters,
    results: cards.results,
    next_steps: cards.nextSteps,
  };
};

export const normalizeSourceCandidate = (candidate: string): "" | "nexusmods" | "loverslab" => {
  const normalized = candidate.trim().toLowerCase();
  if (normalized.includes("nexusmods") || normalized.includes("nexus")) {
    return "nexusmods";
  }
  if (normalized.includes("loverslab") || normalized.includes("lovers")) {
    return "loverslab";
  }
  return "";
};

export const sourceCandidateLabel = (candidate: string): string => {
  const source = normalizeSourceCandidate(candidate);
  if (source === "nexusmods") return "NexusMods";
  if (source === "loverslab") return "LoversLab";
  return candidate;
};

export const scopeFieldLabel = (field: string): string => {
  const key = field.trim().toLowerCase();
  if (key === "game") return "游戏";
  if (key === "source") return "来源";
  if (key === "keywords") return "关键词";
  if (key === "category" || key === "categories") return "类型/风格";
  return field;
};

export const reviewTargetLabel = (target: string): string => {
  const key = target.trim().toLowerCase();
  if (key === "memory_signals") return "记忆信号";
  if (key === "context_slots") return "上下文槽位";
  return target;
};

export const sourceCandidateQuestion = (candidate: string): string => {
  const label = sourceCandidateLabel(candidate);
  return `继续查 ${label} 来源的结果`;
};

export const scopeFieldQuestion = (field: string): string => {
  const key = field.trim().toLowerCase();
  if (key === "game") return "我想限定目标游戏";
  if (key === "source") return "我想指定检索来源";
  if (key === "keywords") return "我想补充更具体的关键词";
  if (key === "category" || key === "categories") return "我想确认类型或风格";
  return `我想补充${scopeFieldLabel(field)}`;
};

export const reviewTargetQuestion = (target: string): string => {
  const key = target.trim().toLowerCase();
  if (key === "memory_signals") return "请解释你参考了哪些记忆信号";
  if (key === "context_slots") return "请解释你继承了哪些上下文条件";
  if (key === "analysis_evidence") return "请说明你理解这个需求的依据";
  return `请解释${reviewTargetLabel(target)}`;
};

export const conflictFieldQuestion = (field: string): string => {
  const key = field.trim().toLowerCase();
  if (key === "game") return "这次目标游戏应该按哪个来查？";
  if (key === "source") return "这次应该优先查哪个来源？";
  if (key === "keywords") return "这次应该保留哪些关键词？";
  if (key === "category" || key === "categories") return "这次应该按哪种类型或风格来查？";
  return `这次${scopeFieldLabel(field)}应该按哪个来查？`;
};

export const extractAssistantSections = (text: string): AssistantSections => {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const sections: AssistantSections = {
    analysis: [],
    evidence: [],
    conclusion: [],
    understanding: [],
    filters: [],
    results: [],
    nextSteps: [],
  };
  const normalize = (line: string) => line.replace(/^[•\-\d\.\)\(]+\s*/, "").trim();

  for (const line of lines) {
    const plain = normalize(line);
    if (!plain) continue;
    if (/^(我理解|理解你的需求|你想找|需求|目标|I understand|You want|理解しました)/i.test(plain)) {
      sections.understanding.push(plain);
      continue;
    }
    if (/^(游戏|類型|类型|時間|时间|来源|來源|source|game|type|filter|条件|條件|条件|來源|ソース)/i.test(plain)) {
      sections.filters.push(plain);
      continue;
    }
    if (/^(找到|命中|候选|候補|推荐|推薦|结果|結果|found|matched)/i.test(plain)) {
      sections.results.push(plain);
      continue;
    }
    if (/^(下一步|建议|建議|你可以|可继续|next step|next action|suggestion)/i.test(plain)) {
      sections.nextSteps.push(plain);
      continue;
    }
  }

  if (sections.understanding.length === 0 && lines.length > 0) {
    sections.understanding.push(lines[0]);
  }
  if (sections.filters.length === 0) {
    const compact = lines.join(" ");
    const gameMatch = compact.match(/《([^》]+)》/);
    if (gameMatch?.[1]) {
      sections.filters.push(`游戏：${gameMatch[1]}`);
    }
    if (/成人|NSFW/i.test(compact)) {
      sections.filters.push("内容分级：NSFW");
    } else if (/SFW|非成人/i.test(compact)) {
      sections.filters.push("内容分级：SFW");
    }
    if (/最近更新|latest|recent/i.test(compact)) {
      sections.filters.push("排序：updated_at_remote (降序)");
    }
  }
  if (sections.results.length === 0 && lines.length > 1) {
    sections.results.push(lines[1]);
  }
  if (sections.nextSteps.length === 0 && lines.length > 2) {
    sections.nextSteps.push(lines[lines.length - 1]);
  }

  return sections;
};
