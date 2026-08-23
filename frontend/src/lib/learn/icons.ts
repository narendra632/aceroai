import {
  Archive,
  BarChart3,
  Brain,
  Clock,
  Coins,
  Database,
  Gauge,
  GraduationCap,
  Layers,
  ListTodo,
  Radio,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
  Trash2,
  Wrench,
} from "lucide-react";
import type { ComponentType } from "react";

import type { IconName } from "./icon-names";

/* Name to component.
 *
 * A `.ts` file, not `.tsx`: there is no JSX here, and a "component file" exporting only a
 * lookup table trips the fast-refresh lint rule for no benefit.
 *
 * `Record<IconName, ...>` is doing real work: adding a name to `icon-names.ts` without
 * adding it here is a type error at build time, rather than an empty box discovered by a
 * reader. That matters because the icon is the fastest signal on the diagram — it is read
 * before the label is.
 */
export const ICONS: Record<IconName, ComponentType<{ className?: string }>> = {
  shield: ShieldCheck,
  save: Save,
  search: Search,
  database: Database,
  layers: Layers,
  sparkles: Sparkles,
  wrench: Wrench,
  radio: Radio,
  archive: Archive,
  graduation: GraduationCap,
  coins: Coins,
  tag: Tag,
  list: ListTodo,
  clock: Clock,
  chart: BarChart3,
  trash: Trash2,
  gauge: Gauge,
  brain: Brain,
};

export type { IconName };
