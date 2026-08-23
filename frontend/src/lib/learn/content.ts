import type { Concept, Diagram, Planned } from "./types";

/* What the Learn section teaches.
 *
 * Rules for editing this file:
 *
 * 1. NEVER write a number the system decides. Write `{recall_k}` and let the endpoint
 *    answer. `memory_recall_k` moved 12 -> 16 in one commit; a literal would already lie.
 * 2. Keep to the budget in types.ts. `npm run lint` fails if you don't. If an idea needs
 *    more, it belongs in docs/ and the panel should link there instead.
 * 3. Explain the idea before the implementation. Someone who has never seen this codebase
 *    should still learn something from a concept card.
 */

// ---------------------------------------------------------------------------------
// Diagram A — one message, end to end
// ---------------------------------------------------------------------------------

export const MESSAGE_FLOW: Diagram = {
  id: "message",
  title: "How a message is answered",
  intro:
    "Everything you type goes through one function, whatever channel it came from. Click any step to see what happens there and why it happens in that order.",
  nodes: [
    { id: "budget", label: "Check the spend ceiling", hint: "before anything is written", icon: "shield", step: 1, col: 1, row: 1 },
    { id: "save", label: "Save your message", icon: "save", step: 2, col: 1, row: 2 },
    { id: "recall", label: "Find the facts that fit", hint: "two searches, fused", icon: "search", step: 3, col: 1, row: 3 },
    { id: "facts", label: "profile_facts", hint: "what it knows about you", icon: "database", col: 2, row: 3, kind: "store" },
    { id: "prompt", label: "Build the prompt", hint: "persona · date · tasks · facts · history", icon: "layers", step: 4, col: 1, row: 4 },
    { id: "history", label: "tasks + messages", icon: "database", col: 2, row: 4, kind: "store" },
    { id: "model", label: "Ask the model", icon: "sparkles", step: 5, col: 1, row: 5, kind: "external" },
    { id: "tools", label: "Run a tool, if it asked", hint: "tasks · journal · memory", icon: "wrench", step: 6, col: 1, row: 6 },
    { id: "services", label: "services/", hint: "one set of rules for everything", icon: "database", col: 2, row: 6, kind: "store" },
    { id: "stream", label: "Stream the reply", hint: "word by word", icon: "radio", step: 7, col: 1, row: 7 },
    { id: "persist", label: "Save the reply", icon: "save", step: 8, col: 1, row: 8 },
    { id: "learn", label: "Learn from the turn", hint: "after you have your answer", icon: "graduation", step: 9, col: 1, row: 9 },
  ],
  edges: [
    { from: "budget", to: "save", label: "within limit" },
    { from: "save", to: "recall" },
    { from: "recall", to: "facts", label: "reads", dashed: true },
    { from: "recall", to: "prompt" },
    { from: "prompt", to: "history", label: "reads", dashed: true },
    { from: "prompt", to: "model" },
    { from: "model", to: "tools" },
    { from: "tools", to: "services", label: "via", dashed: true },
    { from: "tools", to: "stream" },
    { from: "stream", to: "persist" },
    { from: "persist", to: "learn" },
    { from: "learn", to: "facts", label: "writes", dashed: true },
  ],
  panels: {
    budget: {
      id: "budget",
      title: "Check the spend ceiling",
      what: "Before anything else, the month's estimated spend is compared against the limit you set in Settings.",
      how: [
        "Runs first — before your message is even saved, so a refused turn leaves no trace",
        "No provider call is made, so a refusal costs nothing",
        "A warning appears at 80% of the limit, before anything stops",
        "Off by default. With no limit set, nothing here changes",
        "Lives in the one brain, so Telegram inherits it without its own code",
      ],
      measured: "Refusing costs zero tokens and writes zero rows.",
      code: ["backend/app/services/budget.py", "backend/app/core/handler.py"],
      reads: [{ label: "Insights, explained", href: "docs/INSIGHTS.md" }],
      concepts: ["one-brain"],
    },
    save: {
      id: "save",
      title: "Save your message",
      what: "Your message is written to the database, and a new conversation is created if this is the first one.",
      how: [
        "Happens before the model is called, so nothing is lost if generation fails",
        "The conversation is titled from your first message",
        "The message id is kept, so a fact learned here can point back at it",
        "Messages longer than {max_input_chars} characters are refused up front",
      ],
      code: ["backend/app/core/handler.py"],
      concepts: ["provenance"],
    },
    recall: {
      id: "recall",
      title: "Find the facts that fit",
      what: "Two searches run over what the system knows about you, and only what they agree on is trusted.",
      how: [
        "One searches by meaning, one by the actual words — they fail in opposite ways",
        "Their positions are fused, not their scores, which are on different scales",
        "A fact both found is kept; a fact one found must clear that search's own bar",
        "{recall_k} is a ceiling, not a target — a question about nothing stored recalls nothing",
        "Best-effort: if it stalls past {memory_recall_timeout_s}s the reply goes ahead without facts",
      ],
      measured: "\"write a python function to reverse a list\" went from 12 facts to 0.",
      code: ["backend/app/core/recall.py"],
      reads: [{ label: "How Acero remembers", href: "docs/MEMORY.md" }],
      concepts: ["embedding", "cosine", "fulltext", "rrf"],
    },
    facts: {
      id: "facts",
      title: "profile_facts",
      what: "Short sentences about you, each stored with a vector so it can be searched by meaning.",
      how: [
        "Written by one function, whether you asked for it or it noticed in passing",
        "Nothing is deleted on suspicion — a near-duplicate is stored and flagged instead",
        "Correcting supersedes rather than overwrites, so the old belief stays readable",
        "Forgetting is a soft delete, so it can be undone",
        "Every vector is {embed_dim} numbers long",
      ],
      measured: "Two different certifications measured 0.098 apart — closer than the {memory_dedup_distance} threshold that used to delete them.",
      code: ["backend/app/services/memory.py", "backend/app/db/models.py"],
      reads: [{ label: "How Acero remembers", href: "docs/MEMORY.md" }],
      concepts: ["supersession", "soft-delete", "one-writer"],
    },
    prompt: {
      id: "prompt",
      title: "Build the prompt",
      what: "The model sees a fresh prompt every turn: who it is, the date, your open tasks, the recalled facts, then the conversation.",
      how: [
        "The persona is read from a file on disk, so it can be changed without a deploy",
        "Up to {context_tasks_limit} open tasks, so it never invents a duplicate",
        "The last {history_limit} messages — older ones drop off rather than growing forever",
        "Facts carry their ids, so it can correct or forget one in a single step",
        "Nothing is remembered between turns except what is in the database",
      ],
      code: ["backend/app/core/composer.py", "docs/SOUL.md"],
      reads: [{ label: "What a message costs", href: "docs/REQUEST-ANATOMY.md" }],
      concepts: ["stateless"],
    },
    history: {
      id: "history",
      title: "tasks + messages",
      what: "Two ordinary tables. The prompt reads from them directly rather than keeping its own copy.",
      how: [
        "Tasks are ordered by urgency, so the most pressing are the ones shown",
        "Deleted rows are filtered in one place, so the model cannot see them",
        "The same rows power the UI, so what you see is what the model sees",
      ],
      code: ["backend/app/services/tasks.py", "backend/app/services/sessions.py"],
      concepts: ["soft-delete", "services"],
    },
    model: {
      id: "model",
      title: "Ask the model",
      what: "The prompt goes to whichever provider you picked in Settings, and the reply streams back as it is written.",
      how: [
        "Gemini or OpenAI — a per-user setting, not a code change",
        "Each provider is behind one interface, so switching changes nothing else",
        "Thinking effort is dialled per turn: low for chat, high when you ask for it",
        "Streaming means the first word arrives long before the last",
        "{tool_count} tools are described to it every turn, so it can act rather than only answer",
      ],
      code: ["backend/app/core/llm.py", "backend/app/core/providers/base.py"],
      concepts: ["streaming", "tool-calling", "reasoning-effort"],
    },
    tools: {
      id: "tools",
      title: "Run a tool, if it asked",
      what: "Instead of answering, the model can ask to do something — add a task, write a journal entry, remember a fact.",
      how: [
        "The result goes back to the model, which then answers or asks again",
        "Capped at {tools_max_iters} rounds, then it must answer in words",
        "A tool never crashes the turn — a failure comes back as data it can explain",
        "It never supplies your user id; every id it passes is checked against you",
      ],
      measured: "A tool call costs 7-20ms. The extra model round costs ~1.2s.",
      code: ["backend/app/core/tools/__init__.py"],
      concepts: ["tool-calling", "services"],
    },
    services: {
      id: "services",
      title: "services/",
      what: "The one place the rules live. Both the buttons in the UI and the assistant's tools go through it.",
      how: [
        "A task you add by tapping and one the assistant adds are validated identically",
        "Memory has exactly one writer, so background learning and your instructions agree",
        "Routes stay thin: they carry data in and out and decide nothing",
        "Errors are raised as meaning, then mapped to HTTP once, at the edge",
      ],
      code: ["backend/app/services/", "backend/app/services/errors.py"],
      concepts: ["services", "one-writer"],
    },
    stream: {
      id: "stream",
      title: "Stream the reply",
      what: "Words are pushed to the browser as they arrive, over a single long-lived HTTP response.",
      how: [
        "Server-Sent Events — a plain HTTP response the server keeps writing to",
        "Separate events for the session id, each word, the facts used, and the end",
        "The browser reveals text slightly smoothed, so it reads rather than stutters",
        "Scrolling up stops the auto-follow, so a long reply is readable while it arrives",
      ],
      code: ["backend/app/api/chat.py", "frontend/src/lib/api.ts"],
      concepts: ["streaming"],
    },
    persist: {
      id: "persist",
      title: "Save the reply",
      what: "The finished reply is stored with the model that wrote it and the tokens it used.",
      how: [
        "Token counts come from the provider, not from an estimate",
        "The cost is worked out and frozen now, from a dated price list",
        "A failed turn is recorded too — a dashboard of only successes hides the problem",
      ],
      code: ["backend/app/core/handler.py", "backend/app/core/pricing.py"],
      concepts: ["frozen-cost"],
    },
    learn: {
      id: "learn",
      title: "Learn from the turn",
      what: "After you have your answer, a second cheaper model reads the exchange and looks for anything durable.",
      how: [
        "Runs after the reply is delivered, so its cost is never felt",
        "It can add and correct, but it is not allowed to delete",
        "It is shown the facts recall already found, so it does not re-propose them",
        "Every error is swallowed — learning must never break answering",
      ],
      code: ["backend/app/core/memory.py"],
      reads: [{ label: "How Acero remembers", href: "docs/MEMORY.md" }],
      concepts: ["one-writer", "background-work"],
    },
  },
};

// ---------------------------------------------------------------------------------
// Diagram B — the money
// ---------------------------------------------------------------------------------

export const COST_FLOW: Diagram = {
  id: "cost",
  title: "What it costs, and how we know",
  intro:
    "Every call to a model is recorded, including the ones you never see. This is how a number ends up on the Insights page, and how a runaway loop gets stopped rather than merely noticed.",
  nodes: [
    { id: "tokens", label: "Count the tokens", hint: "per round, not per turn", icon: "tag", step: 1, col: 1, row: 1 },
    { id: "price", label: "Price it, now", hint: "frozen at write time", icon: "coins", step: 2, col: 1, row: 2 },
    { id: "turns", label: "turns", hint: "one row per model call", icon: "database", col: 1, row: 3, kind: "store" },
    { id: "spans", label: "spans", hint: "the stages inside it", icon: "clock", col: 2, row: 3, kind: "store" },
    { id: "rollup", label: "Roll up the day", icon: "archive", step: 3, col: 1, row: 4 },
    { id: "daily", label: "daily_usage", hint: "kept forever", icon: "database", col: 2, row: 4, kind: "store" },
    { id: "prune", label: "Delete the detail", hint: "after the window", icon: "trash", step: 4, col: 1, row: 5 },
    { id: "insights", label: "Read it on Insights", icon: "chart", step: 5, col: 1, row: 6 },
    { id: "ceiling", label: "Stop at the ceiling", hint: "the next turn is refused", icon: "gauge", step: 6, col: 1, row: 7 },
  ],
  edges: [
    { from: "tokens", to: "price" },
    { from: "price", to: "turns" },
    { from: "turns", to: "spans", label: "detail", dashed: true },
    { from: "turns", to: "rollup" },
    { from: "rollup", to: "daily", label: "writes", dashed: true },
    { from: "rollup", to: "prune" },
    { from: "prune", to: "insights" },
    { from: "insights", to: "ceiling" },
  ],
  panels: {
    tokens: {
      id: "tokens",
      title: "Count the tokens",
      what: "Providers charge per token in and per token out, and they report both after each request.",
      how: [
        "A turn that uses tools makes several requests, so the counts are added up",
        "Thinking tokens are counted separately — they are billed at the output rate",
        "Embeddings and background learning are counted too, not just the reply",
      ],
      measured: "Counting only the last round under-reported a real turn as 1,500/90 instead of 2,500/130.",
      code: ["backend/app/core/providers/base.py"],
      concepts: ["tokens", "background-work"],
    },
    price: {
      id: "price",
      title: "Price it, now",
      what: "Cost is worked out at the moment of the call, from a price list kept in the code, and stored as a number.",
      how: [
        "Frozen at write time — a later price change never rewrites last month",
        "The version of the price list is stored alongside, so the sum is explainable",
        "A model with no known price is recorded as unpriced rather than as zero",
        "This is an estimate. The app never sees your actual provider invoice",
      ],
      code: ["backend/app/core/pricing.py"],
      reads: [{ label: "Insights, explained", href: "docs/INSIGHTS.md" }],
      concepts: ["frozen-cost"],
    },
    turns: {
      id: "turns",
      title: "turns",
      what: "One row for every model call: what it cost, how long it took, whether it worked.",
      how: [
        "Chat, memory extraction and embeddings all appear, so nothing is invisible",
        "A failed call is recorded with why it failed",
        "No message text is ever stored here — shape and cost only",
        "Kept for {turn_retention_days} days",
      ],
      code: ["backend/app/db/models.py"],
      concepts: ["observability"],
    },
    spans: {
      id: "spans",
      title: "spans",
      what: "The stages inside one turn, each timed: saving, recall, building the prompt, each model round, each tool.",
      how: [
        "This is what the waterfall on Insights draws",
        "'First word appears' is a moment, not a duration, and is drawn apart",
        "Recall records which search found each fact, not just how many",
        "Kept for {span_retention_days} days — the shortest window, and the least missed",
      ],
      measured: "This shape made a 12-second embedding stall obvious in one glance.",
      code: ["backend/app/core/telemetry.py"],
      concepts: ["observability"],
    },
    rollup: {
      id: "rollup",
      title: "Roll up the day",
      what: "Before old detail is deleted, each day's totals are summed into a permanent row.",
      how: [
        "Runs once a day, on the first call of the day — no scheduler needed yet",
        "The boundary is taken from the data, so there can be no gap and no double count",
        "Totals survive; the per-turn detail behind them does not",
      ],
      code: ["backend/app/services/retention.py"],
      concepts: ["retention"],
    },
    daily: {
      id: "daily",
      title: "daily_usage",
      what: "One row per day per model: calls, tokens, cost. Small enough to keep forever.",
      how: [
        "This is what makes a year-long spend chart possible on a small disk",
        "Speed and error detail are lost with the spans; money and volume are not",
      ],
      measured: "A turn row costs ~319 bytes, a span ~183. The rollup replaces thousands with one.",
      code: ["backend/app/services/insights.py"],
      concepts: ["retention"],
    },
    prune: {
      id: "prune",
      title: "Delete the detail",
      what: "Once a day is rolled up, its turns and spans are deleted so the tables cannot outgrow the disk.",
      how: [
        "A day is only pruned if its totals are already saved",
        "Runs with a short lock timeout, so housekeeping can never block a reply",
        "Three tiers: spans go first, turns later, the rollup never",
      ],
      code: ["backend/app/services/retention.py"],
      reads: [{ label: "Deployment runbook", href: "docs/DEPLOY.md" }],
      concepts: ["retention"],
    },
    insights: {
      id: "insights",
      title: "Read it on Insights",
      what: "Spend, volume, latency and errors, plus a per-turn waterfall for any call still inside the window.",
      how: [
        "Strictly read-only — nothing on that page changes anything",
        "Background work is shown separately, because it is easy to forget it exists",
        "Any past turn can also show which facts it used",
      ],
      code: ["backend/app/api/insights.py"],
      reads: [{ label: "Insights, explained", href: "docs/INSIGHTS.md" }],
      concepts: ["observability"],
    },
    ceiling: {
      id: "ceiling",
      title: "Stop at the ceiling",
      what: "Watching the cost is not the same as controlling it, so a monthly limit refuses the next turn.",
      how: [
        "Set in Settings, off by default",
        "A band appears at 80%, so the stop is never a surprise",
        "When it stops, the composer says so and offers a way to raise it",
        "Checked in the one brain, so every channel obeys it",
      ],
      code: ["backend/app/services/budget.py"],
      concepts: ["one-brain"],
    },
  },
};

// ---------------------------------------------------------------------------------
// Concepts — the ideas underneath, each useful outside this codebase
// ---------------------------------------------------------------------------------

export const CONCEPTS: Concept[] = [
  {
    id: "embedding",
    group: "memory",
    title: "Embeddings",
    what: "A sentence turned into a list of numbers, positioned so that similar meanings land near each other.",
    how: [
      "A model reads the text and outputs a fixed-length list — here, {embed_dim} numbers",
      "'Where do I work' lands near 'Narendra works at TCS' with no shared words",
      "The numbers only mean something relative to the model that made them",
      "Swapping the model invalidates every stored vector — same length, different meaning",
    ],
    code: ["backend/app/core/llm.py"],
    concepts: ["cosine"],
  },
  {
    id: "cosine",
    group: "memory",
    title: "Cosine distance",
    what: "How far apart two embeddings point. 0 means the same direction, 1 means unrelated.",
    how: [
      "It compares direction, not length, so sentence length barely matters",
      "It measures subject matter — not whether two sentences say the same thing",
      "All facts about one person crowd into a narrow band, which limits what it can decide",
    ],
    measured: "Every fact about one person falls between 0.30 and 0.58 of any question about them.",
    code: ["backend/app/core/recall.py"],
    reads: [{ label: "How Acero remembers", href: "docs/MEMORY.md" }],
  },
  {
    id: "floor",
    group: "memory",
    title: "Why a relevance cut-off failed",
    what: "The obvious fix — ignore anything further than X — was measured, and it could not work.",
    how: [
      "Set the line tight and real answers disappear; set it loose and it filters nothing",
      "'hello' scored closer to stored facts than genuine matches for other questions",
      "The problem is not the number. Distance answers the wrong question",
      "The fix was a second, different search — not a better threshold",
    ],
    measured: "A 0.40 cut-off returned zero facts for \"where do I work\", whose answer sits at 0.406.",
    code: ["backend/app/core/recall.py"],
  },
  {
    id: "fulltext",
    group: "memory",
    title: "Keyword search and stemming",
    what: "Searching by the actual words, using an index built backwards: word to the list of facts containing it.",
    how: [
      "One dictionary lookup, not a comparison against every fact — so it stays fast",
      "Words are reduced to a stem, so 'works', 'working' and 'work' all match",
      "Filler words are dropped; they carry no information about which fact you want",
      "Only the {lexical_terms_max} rarest words of your message are used",
      "Rare words identify a fact; common ones match everything and are thrown away",
    ],
    measured: "A word appearing in every fact costs 219ms at 20,000 facts — which is why they are dropped.",
    code: ["backend/app/core/recall.py"],
  },
  {
    id: "rrf",
    group: "memory",
    title: "Fusing two searches by rank",
    what: "Two rankings are combined by their positions rather than their scores, so no scale has to be normalised.",
    how: [
      "Each result scores 1 / ({rrf_k} + its position) in each list, and the scores add up",
      "Being found by both roughly doubles the score — agreement is the signal",
      "Scores are never compared directly: 0.30-0.58 and 0.00-0.10 are not the same units",
      "Needs no tuning when either search changes, because magnitudes are discarded",
      "Top-ups are capped: {vector_only_max} by meaning, {lexical_only_max} by word",
    ],
    measured: "Found by both scores ~0.032; found by one scores ~0.015. That gap is the whole mechanism.",
    code: ["backend/app/core/recall.py"],
    concepts: ["cosine", "fulltext"],
  },
  {
    id: "hnsw",
    group: "data",
    title: "Searching vectors quickly (HNSW)",
    what: "An index that finds near neighbours without comparing your question against every stored vector.",
    how: [
      "It builds layers of shortcuts, so a search hops close then refines",
      "Approximate by design — it trades a tiny chance of a miss for a large speed-up",
      "The index must match what the query filters on, or the database ignores it",
    ],
    measured: "On 800 facts, the right index took a neighbour search from 5,619ms to 170ms.",
    code: ["backend/alembic/versions/f6a7b8c9d0e1_006_live_facts_hnsw.py"],
  },
  {
    id: "supersession",
    group: "memory",
    title: "Superseding instead of overwriting",
    what: "Correcting a fact writes a new row and retires the old one, rather than changing it in place.",
    how: [
      "The old belief stays readable, so you can see what it used to think",
      "The retired row points at its replacement, so history is a chain, not a guess",
      "Only the active row is ever shown to the model",
      "Editing metadata is different — that is the same belief, relabelled, and updates in place",
    ],
    code: ["backend/app/services/memory.py"],
  },
  {
    id: "soft-delete",
    group: "data",
    title: "Soft delete",
    what: "Deleting marks a row as gone instead of removing it, so the action can be undone.",
    how: [
      "One filter, defined in exactly one place, hides them from every reader",
      "That single definition is what stops a deleted row leaking back into the model",
      "Undo is then just clearing the mark",
    ],
    code: ["backend/app/services/memory.py"],
  },
  {
    id: "one-writer",
    group: "memory",
    title: "One writer",
    what: "Every path that changes memory goes through one function, so the rules exist once.",
    how: [
      "Your explicit instruction and the background learner obey identical rules",
      "Validation, duplicate judgement and history live in that one place",
      "Two implementations would drift, and the duplicate rule would exist twice",
    ],
    code: ["backend/app/services/memory.py"],
  },
  {
    id: "one-brain",
    group: "delivery",
    title: "One brain",
    what: "Every message from every channel runs through the same function. Channels only carry data.",
    how: [
      "Telegram and the web app share behaviour without sharing code",
      "A new rule — like the spend ceiling — is inherited by every channel at once",
      "A channel that could decide things is a second place for behaviour to diverge",
    ],
    code: ["backend/app/core/handler.py"],
  },
  {
    id: "services",
    group: "delivery",
    title: "One source of truth for rules",
    what: "Business rules live in a service layer that both the API and the assistant call.",
    how: [
      "A task added by tapping and one added by the assistant are the same operation",
      "Routes carry data and decide nothing, so they stay short",
      "Errors are raised as meaning and translated to HTTP once, at the edge",
    ],
    code: ["backend/app/services/", "backend/app/api/"],
  },
  {
    id: "streaming",
    group: "delivery",
    title: "Streaming a reply (SSE)",
    what: "One HTTP response the server keeps writing to, so words appear as they are generated.",
    how: [
      "Plain HTTP — no second protocol, no socket to keep alive",
      "Each frame is labelled, so the browser can tell a word from an event",
      "The database is never touched mid-stream; it is written before and after",
      "Stopping is just abandoning the response",
    ],
    code: ["backend/app/api/chat.py"],
  },
  {
    id: "tool-calling",
    group: "model",
    title: "Tool calling",
    what: "The model is given a list of functions it may ask for, and can reply with a request instead of an answer.",
    how: [
      "It sees names, descriptions and argument shapes — never any code",
      "It decides whether to act; most turns it simply answers",
      "The result is fed back and it continues, up to {tools_max_iters} rounds",
      "A result must be honest: a failure it can read beats a silence it will narrate over",
    ],
    code: ["backend/app/core/tools/__init__.py"],
  },
  {
    id: "reasoning-effort",
    group: "model",
    title: "Reasoning effort",
    what: "Thinking models can be told how hard to think, trading latency and cost against depth.",
    how: [
      "Low for ordinary chat, high when you explicitly ask for more",
      "Thinking tokens are billed at the output rate even though you never see them",
      "The budget for thinking is separate from the budget for the answer",
    ],
    code: ["backend/app/core/providers/openai_provider.py"],
  },
  {
    id: "tokens",
    group: "model",
    title: "Tokens",
    what: "Models read and write in tokens — chunks of a few characters — and both directions are billed.",
    how: [
      "The prompt is rebuilt every turn, so its size is paid every turn",
      "Roughly four characters per token in English",
      "Trimming the prompt is the cheapest lever there is",
    ],
    measured: "Recall going from a fixed 12 facts to 0-8 saves roughly 100-200 tokens per turn.",
    reads: [{ label: "What a message costs", href: "docs/REQUEST-ANATOMY.md" }],
  },
  {
    id: "stateless",
    group: "model",
    title: "The model remembers nothing",
    what: "Each request is complete on its own. Continuity is an illusion the prompt creates.",
    how: [
      "The last {history_limit} messages are re-sent every turn",
      "Anything not in the prompt does not exist for that turn",
      "This is exactly why memory has to be built rather than assumed",
    ],
    code: ["backend/app/core/composer.py"],
  },
  {
    id: "frozen-cost",
    group: "data",
    title: "Freezing a derived value",
    what: "Cost is computed once, when the call happens, and stored — rather than recalculated on read.",
    how: [
      "A price change later must not rewrite what last month cost",
      "The price list version is stored with it, so any total can be explained",
      "The opposite rule applies to confidence, which is derived on read",
    ],
    code: ["backend/app/core/pricing.py"],
  },
  {
    id: "retention",
    group: "data",
    title: "Keeping less, forever",
    what: "Detailed records are summarised before being deleted, so history survives without unbounded storage.",
    how: [
      "Three tiers: fine detail briefly, per-call rows longer, daily totals forever",
      "Summarise first, delete second — never the other way round",
      "The boundary comes from the data, so no day is counted twice or lost",
    ],
    code: ["backend/app/services/retention.py"],
  },
  {
    id: "observability",
    group: "data",
    title: "Recording what happened",
    what: "Every call records its cost, timing and outcome, so questions can be answered afterwards.",
    how: [
      "Written after the reply, so a recording failure can never affect an answer",
      "Failures are recorded too — a log of only successes hides the problem",
      "Shape and cost only. Message text is never written to a trace",
    ],
    code: ["backend/app/core/telemetry.py"],
  },
  {
    id: "provenance",
    group: "data",
    title: "Provenance",
    what: "A learned fact records which message it came from, so 'where did you get that?' has an answer.",
    how: [
      "Without it a wrong belief can only be deleted, never argued with",
      "The stored id is a message; the conversation is resolved when you ask",
      "The same idea powers the list of facts shown under each reply",
    ],
    code: ["backend/app/services/memory.py"],
  },
  {
    id: "background-work",
    group: "delivery",
    title: "Work that happens after the answer",
    what: "Learning from a turn runs once the reply is delivered, in its own session, swallowing every error.",
    how: [
      "Its latency is never felt, because nobody is waiting on it",
      "It gets its own database session — the request's is already finished",
      "It is billed, so it is recorded, or it would be invisible spend",
    ],
    measured: "Background work is around 4% of spend and a third of all calls.",
    code: ["backend/app/core/memory.py"],
  },
  {
    id: "migrations",
    group: "data",
    title: "Migrations",
    what: "Schema changes are scripts applied in order, so every environment reaches the same shape.",
    how: [
      "Each has an up and a down, and both are exercised before shipping",
      "They run automatically on deploy, before the app starts",
      "Tested against an empty database and against one holding real rows",
    ],
    code: ["backend/alembic/versions/"],
  },
];

// ---------------------------------------------------------------------------------
// Planned — never mixed in with what exists
// ---------------------------------------------------------------------------------

export const PLANNED: Planned[] = [
  {
    id: "jobs",
    title: "Scheduled jobs",
    what: "A day-end summary and proactive nudges, running on a timer rather than waiting to be asked.",
    trigger: "Next on the roadmap — the package exists and is empty.",
  },
  {
    id: "barnes-hut",
    title: "Faster knowledge map layout",
    what: "The map compares every fact with every other one, which stops being free as memory grows.",
    trigger: "At {graph_warn_at} facts the page says so, before anything is hidden.",
  },
  {
    id: "bm25",
    title: "A better keyword ranker",
    what: "The current one filters well but barely ranks — it has no sense of how rare a word is.",
    trigger: "Around 1,000 facts, where rarity becomes real signal rather than noise.",
  },
  {
    id: "conflicts",
    title: "Conflict review",
    what: "Two contradicting facts can both sit in memory. Nothing sweeps for pairs already stored.",
    trigger: "Needs a batched model call — distance alone provably cannot judge it.",
  },
  {
    id: "pwa",
    title: "Install it like an app, with push",
    what: "A home-screen app with notifications, which would retire the Telegram channel.",
    trigger: "After scheduled jobs — there is nothing to notify you about yet.",
  },
];

export const DIAGRAMS = [MESSAGE_FLOW, COST_FLOW];
