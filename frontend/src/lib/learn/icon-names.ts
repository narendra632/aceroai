/* The icons a diagram node may use, as plain strings.
 *
 * Deliberately separate from the components. `content.ts` and the content checker both
 * read this file, and the checker runs in bare Node — so nothing here may import a React
 * component or the check would have to load the whole icon library to validate a name.
 *
 * `icons.tsx` maps these to actual components, and its `Record<IconName, ...>` type makes
 * a missing mapping a compile error rather than a blank square on the page.
 */

export const ICON_NAMES = [
  "shield",
  "save",
  "search",
  "database",
  "layers",
  "sparkles",
  "wrench",
  "radio",
  "archive",
  "graduation",
  "coins",
  "tag",
  "list",
  "clock",
  "chart",
  "trash",
  "gauge",
  "brain",
] as const;

export type IconName = (typeof ICON_NAMES)[number];
