/* Checks the Learn content against the repository it describes.
 *
 * Run by `npm run lint`, so it happens on every CI run with no new dependency and no test
 * framework. This is not unit testing — there is no logic here to test. It is validating
 * DATA that happens to live in .ts files, which is closer to a spellchecker.
 *
 * The failure it exists to prevent is silent rot. A panel saying "see backend/app/core/
 * recall.py" is a STRING: rename the file and TypeScript sees nothing wrong, the build
 * passes, CI is green, and the page quietly teaches something false. Same for a `{recall_k}`
 * whose setting was removed, or a concept id after a rename.
 *
 * It cannot check that the prose is true — nothing can. It checks that every mechanical
 * claim resolves, which is where staleness actually gets in.
 *
 * Node 22 strips TypeScript natively, so the content is imported rather than parsed.
 */

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");

const { DIAGRAMS, CONCEPTS, PLANNED } = await import("../src/lib/learn/content.ts");
const { BUDGET } = await import("../src/lib/learn/types.ts");
// Icon NAMES only. `icons.tsx` maps them to components and pulls in lucide-react; this
// check must stay importable from bare Node, so the names live in their own module.
const { ICON_NAMES } = await import("../src/lib/learn/icon-names.ts");
const ICONS = new Set(ICON_NAMES);

const problems = [];
const fail = (where, message) => problems.push(`${where}: ${message}`);

// --- what the backend actually serves ---------------------------------------------
//
// Read from the response model rather than by calling the API, so this runs offline and in
// CI. The backend has its own test asserting the model matches the endpoint, so checking
// against the model is checking against the endpoint.
const SCHEMA = readFileSync(join(REPO, "backend", "app", "api", "schemas.py"), "utf8");
const modelBody = SCHEMA.split("class LearnConstants(BaseModel):")[1];
if (!modelBody) {
  console.error("could not find LearnConstants in backend/app/api/schemas.py");
  process.exit(1);
}
const SERVED = new Set(
  [...modelBody.split(/\nclass /)[0].matchAll(/^\s{4}(\w+):\s*(?:int|float)\s*$/gm)].map(
    (m) => m[1],
  ),
);
if (SERVED.size === 0) {
  console.error("parsed zero fields from LearnConstants — the check would pass vacuously");
  process.exit(1);
}

const CONCEPT_IDS = new Set(CONCEPTS.map((c) => c.id));
const PLACEHOLDER = /\{(\w+)\}/g;

// --- the checks --------------------------------------------------------------------

function checkText(where, text) {
  for (const [, key] of text.matchAll(PLACEHOLDER)) {
    if (!SERVED.has(key)) {
      fail(where, `uses {${key}}, which /api/learn/constants does not serve`);
    }
  }
}

function checkExplanation(where, e) {
  if (!e.title || e.title.length > BUDGET.title) {
    fail(where, `title is ${e.title?.length ?? 0} chars, limit is ${BUDGET.title}`);
  }
  if (!e.what || e.what.length > BUDGET.what) {
    fail(where, `"what" is ${e.what?.length ?? 0} chars, limit is ${BUDGET.what}`);
  }
  if (!Array.isArray(e.how) || e.how.length === 0) {
    fail(where, `has no "how" bullets`);
  } else if (e.how.length > BUDGET.howBullets) {
    fail(where, `has ${e.how.length} bullets, limit is ${BUDGET.howBullets}`);
  }
  for (const [i, bullet] of (e.how ?? []).entries()) {
    if (bullet.length > BUDGET.howBullet) {
      fail(where, `bullet ${i + 1} is ${bullet.length} chars, limit is ${BUDGET.howBullet}`);
    }
  }

  checkText(where, [e.title, e.what, e.measured ?? "", ...(e.how ?? [])].join(" "));

  for (const path of e.code ?? []) {
    if (!existsSync(join(REPO, path))) {
      fail(where, `points at "${path}", which does not exist`);
    }
  }
  for (const read of e.reads ?? []) {
    if (!existsSync(join(REPO, read.href))) {
      fail(where, `links to "${read.href}", which does not exist`);
    }
  }
  for (const id of e.concepts ?? []) {
    if (!CONCEPT_IDS.has(id)) {
      fail(where, `references concept "${id}", which is not defined`);
    }
  }
}

for (const diagram of DIAGRAMS) {
  const nodeIds = new Set(diagram.nodes.map((n) => n.id));

  // A dangling edge is legal to draw and impossible to notice — the line simply goes
  // nowhere. Caught here rather than rendered as a guess.
  for (const edge of diagram.edges) {
    for (const end of [edge.from, edge.to]) {
      if (!nodeIds.has(end)) {
        fail(`${diagram.id}`, `edge references node "${end}", which does not exist`);
      }
    }
  }

  // Every node must open something. A node that does nothing when clicked is worse than
  // a node that is not clickable, because the reader tries twice.
  for (const node of diagram.nodes) {
    if (!diagram.panels[node.id]) {
      fail(`${diagram.id}/${node.id}`, `node has no panel`);
    }
    checkText(`${diagram.id}/${node.id}`, `${node.label} ${node.hint ?? ""}`);
    // A typo here renders as an empty square, which reads as a loading bug rather than a
    // mistake — so it fails the build instead.
    if (node.icon && !ICONS.has(node.icon)) {
      fail(`${diagram.id}/${node.id}`, `icon "${node.icon}" is not in icon-names.ts`);
    }
  }

  // Step numbers are the reader's sense of order, so they must actually be an order:
  // 1..N with nothing skipped and nothing repeated.
  const steps = diagram.nodes
    .filter((n) => n.step !== undefined)
    .map((n) => n.step)
    .sort((a, b) => a - b);
  for (const [i, step] of steps.entries()) {
    if (step !== i + 1) {
      fail(`${diagram.id}`, `step numbers are ${steps.join(", ")} — expected 1..${steps.length}`);
      break;
    }
  }
  for (const id of Object.keys(diagram.panels)) {
    if (!nodeIds.has(id)) {
      fail(`${diagram.id}/${id}`, `panel has no node — it can never be opened`);
    }
    checkExplanation(`${diagram.id}/${id}`, diagram.panels[id]);
  }
  checkText(`${diagram.id}`, `${diagram.title} ${diagram.intro}`);
}

const seen = new Set();
for (const concept of CONCEPTS) {
  if (seen.has(concept.id)) fail(`concept/${concept.id}`, "duplicate id");
  seen.add(concept.id);
  if (!concept.group) fail(`concept/${concept.id}`, "has no group");
  checkExplanation(`concept/${concept.id}`, concept);
}

for (const item of PLANNED) {
  if (!item.what || item.what.length > BUDGET.what) {
    fail(`planned/${item.id}`, `"what" is ${item.what?.length ?? 0} chars`);
  }
  if (!item.trigger) fail(`planned/${item.id}`, "has no trigger");
  checkText(`planned/${item.id}`, `${item.title} ${item.what} ${item.trigger}`);
}

// --- report -------------------------------------------------------------------------

const counted =
  DIAGRAMS.reduce((n, d) => n + Object.keys(d.panels).length, 0) +
  CONCEPTS.length +
  PLANNED.length;

if (problems.length) {
  console.error(`\nLearn content: ${problems.length} problem(s)\n`);
  for (const p of problems) console.error(`  ${p}`);
  console.error("");
  process.exit(1);
}

console.log(
  `Learn content OK — ${counted} explanations, ${SERVED.size} live constants available.`,
);
