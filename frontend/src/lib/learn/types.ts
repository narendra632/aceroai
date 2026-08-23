/* The shape of everything the Learn section teaches.
 *
 * Content lives here as typed data rather than in the database or in loose markdown, for
 * one reason: it describes the code, so it has to move in the same commit as the code and
 * be reviewed in the same diff. A sentence explaining how recall works must not survive a
 * change to recall.
 *
 * The structure is also what makes the content checkable. `code` is a repo path, `reads` is
 * a doc, `concepts` are ids — all three are verified to resolve by
 * `scripts/check-learn-content.mjs`, which runs as part of `npm run lint`. Prose can only
 * be kept honest by whoever edits it; references can be checked.
 */

/** A number the running system decides. Written as `{recall_k}` in any text field and
 *  resolved at view time from `GET /api/learn/constants` — never hardcoded, because a
 *  quoted number that has drifted teaches something false with the authority of a fact. */
export type ConstantKey = string;

export type Explanation = {
  id: string;
  /** ≤ 60 chars. */
  title: string;
  /** One sentence, ≤ 140 chars. What this *is*, before any detail. */
  what: string;
  /** ≤ 5 bullets, ≤ 120 chars each. How it works. */
  how: string[];
  /** At most ONE measured figure. The thing that makes it real rather than plausible. */
  measured?: string;
  /** Repo-relative paths. Checked to exist. */
  code?: string[];
  /** Where the full detail lives, for when the budget above is not enough. */
  reads?: { label: string; href: string }[];
  /** Concept ids this leans on, rendered as links into the Concepts section. */
  concepts?: string[];
};

export type FlowNodeSpec = {
  id: string;
  label: string;
  hint?: string;
  col: number;
  row: number;
  kind?: "stage" | "store" | "external" | "planned";
};

export type FlowEdgeSpec = {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
};

export type Diagram = {
  id: string;
  title: string;
  /** One short paragraph above the diagram. The question it answers. */
  intro: string;
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  /** Keyed by node id. Every node must have one. */
  panels: Record<string, Explanation>;
};

export type Concept = Explanation & {
  /** A one-word grouping for the card grid: "memory", "model", "data", "delivery". */
  group: string;
};

export type Planned = {
  id: string;
  title: string;
  /** ≤ 140 chars. */
  what: string;
  /** What has to be true before this gets built. The project schedules by measurement,
   *  not by date, so this is a number rather than a quarter. */
  trigger: string;
};

/** The budget from the design, expressed once so the checker and the authors agree.
 *  "Not too much text" was the brief; a limit that is checked is a limit that holds. */
export const BUDGET = {
  title: 60,
  what: 140,
  howBullets: 5,
  howBullet: 120,
} as const;
