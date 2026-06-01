export function boundedIntegerParam(
  value: number,
  {
    min,
    max,
  }: {
    min: number;
    max?: number;
  },
): string {
  const integer = Number.isFinite(value) ? Math.floor(value) : min;
  const bounded = max === undefined ? Math.max(min, integer) : Math.min(max, Math.max(min, integer));
  return String(bounded);
}

export function positiveIntegerParam(value: number): string | undefined {
  if (!Number.isInteger(value) || value <= 0) {
    return undefined;
  }
  return String(value);
}
