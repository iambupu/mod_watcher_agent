export function parseIntegerInput(
  raw: string,
  {
    min,
    max,
    allowEmpty = false,
  }: {
    min?: number;
    max?: number;
    allowEmpty?: boolean;
  } = {},
): number | null | undefined {
  const trimmed = raw.trim();
  if (!trimmed) {
    return allowEmpty ? undefined : null;
  }

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return null;
  }

  const integer = Math.floor(parsed);
  if (min !== undefined && integer < min) {
    return null;
  }
  if (max !== undefined && integer > max) {
    return max;
  }
  return integer;
}

export function parseWholeIntegerInput(
  raw: string,
  {
    min,
    max,
    allowEmpty = false,
  }: {
    min?: number;
    max?: number;
    allowEmpty?: boolean;
  } = {},
): number | null | undefined {
  const trimmed = raw.trim();
  if (!trimmed) {
    return allowEmpty ? undefined : null;
  }

  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed)) {
    return null;
  }
  if (min !== undefined && parsed < min) {
    return null;
  }
  if (max !== undefined && parsed > max) {
    return null;
  }
  return parsed;
}

export function clampIntegerInput(
  raw: string,
  {
    min,
    max,
    fallback,
  }: {
    min: number;
    max: number;
    fallback: number;
  },
): number {
  const trimmed = raw.trim();
  if (!trimmed) {
    return fallback;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.floor(parsed)));
}

export function clampNumberInput(
  raw: string,
  {
    min,
    max,
    fallback,
  }: {
    min: number;
    max: number;
    fallback: number;
  },
): number {
  const parsed = Number(raw.trim());
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

export function numberValue(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function nonNegativeNumberValue(value: unknown): number | null {
  const parsed = numberValue(value);
  return parsed !== null && parsed >= 0 ? parsed : null;
}
