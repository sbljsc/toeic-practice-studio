/** Whether a target can be reached by choosing whole groups only. */
export function canAssembleTarget(target: number, groupSizes: number[]): boolean {
  if (!Number.isInteger(target) || target < 0 || groupSizes.some((size) => !Number.isInteger(size) || size <= 0)) return false;
  const reachable = new Set([0]);
  for (const size of groupSizes) {
    for (const count of [...reachable]) if (count + size <= target) reachable.add(count + size);
  }
  return reachable.has(target);
}
