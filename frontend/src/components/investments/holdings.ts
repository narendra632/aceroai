/** The chart's time ranges and the table's sort keys, shared by the page and the Holdings tab.
 *  Kept out of the component file so fast refresh can treat that file as components only. */

export const RANGES = [
  { key: "3m", label: "3M", days: 90 },
  { key: "6m", label: "6M", days: 182 },
  { key: "1y", label: "1Y", days: 365 },
  { key: "3y", label: "3Y", days: 1095 },
  { key: "all", label: "All", days: null },
] as const;

export type RangeKey = (typeof RANGES)[number]["key"];

export type SortKey = "symbol" | "cost" | "value" | "gain";
