import { parseBoolean } from "@/utils/boolean";

export function isAdultContent(value: unknown): boolean {
  return parseBoolean(value, false);
}
