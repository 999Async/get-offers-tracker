/** Preserve the distinction between unknown, zero, and small positive costs. */
export function formatCost(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "未知";
  if (value > 0 && value < 0.000001) return "<0.000001";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
}
