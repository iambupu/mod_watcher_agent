export function positiveIntegerIds(values: unknown): number[] {
  if (!Array.isArray(values)) return [];
  return values.filter((value): value is number => (
    typeof value === "number"
    && Number.isInteger(value)
    && value > 0
  ));
}
