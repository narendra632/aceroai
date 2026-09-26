# Investments Phase 2, stage 1 — the framework as data

## Why

Phase 2 scores companies against a theory about India: ten things the country must build, the
bottlenecks in the way, and who clears them. Nothing of that theory existed in the code.

Narendra raised the objection that shaped this stage, and it was right. A research pass over
his framework documents produced crossing counts — how many national imperatives each
bottleneck blocks — for the eight bottlenecks in his "Master Bottleneck Map", and defaulted
the other twenty-two to **1**. His words: *"some are mapped to 6 and some default to 1, that
should not be the case... I think there is something wrong here."*

There was. That difference is not a finding about India. It is a difference in **how
completely each section of his notes happens to be written**. Ammunition would have scored
structurally narrow because that section is short, not because replacing consumed munitions
serves one imperative. A gap in a write-up would have been scored as a fact about the world.

His second point generalised it: *"the AI should be able to deduce the bottleneck a company
covers"*. Correct, and it separates two things that were being conflated. The **taxonomy** is
his theory and should be stored and versioned. The **mapping of a company into it** must be
deduced, because that is where every new stock arrives.

## What Changes

**One rule.** Nothing about the framework is a constant in the code. Every row was either
derived from his documents carrying the line that justifies it, or proposed by the model
carrying evidence — and either way it **scores zero until a person agrees once**.

- **`framework_versions` holds the theory**; `ab_mappings` holds where each company sits.
  Split because companies are added often and the theory changes rarely: folding them
  together would make adding a watchlist name look like a new epoch of the framework, and
  every past decision would appear to have been made under different rules.

- **`crossings_status` replaces the default of 1.** `CONFIRMED` is stated in his Master Map.
  `PARTIAL` means "at least this many, and the rest was never established" — it scores what is
  known and the interface calls the figure a **floor**, not a finding.

- **Four flows cover every way a company can arrive**, which closes the "are we covered in
  future" question: an existing bottleneck (propose + approve), a *new* bottleneck (propose
  the bottleneck too, which is a new framework version), a sector with no fair multiple
  (flagged rather than silently defaulted), and off-framework by construction.

- **Two holes found by walking the scenarios, and closed.**
  - `off_framework` — the framework asks what INDIA must build, so no imperative applies to
    SpaceX. It scores **`None`, not zero**: "this test does not apply" is a different answer
    from "measured and found wanting".
  - `review_after` — a mapping says what a company does *today*. Kaynes is moving from
    contract electronics into chip packaging; a mapping approved two years ago would keep
    scoring the old business. A mapping expires and is re-proposed.

- **The data**: 10 imperatives, 31 bottlenecks, 19 fair multiples, sector labels on all 11
  Indian equities, and 7 watchlist companies added. Without a watchlist the system can only
  say "hold" or "sell" — a research analyst that can only discuss what you already own is a
  bookkeeper with opinions.

- **Three multiples changed from the research pass**, on his instruction: Apar 24 → **26** and
  Rolex 18 → **20** (both his own numbers, which the pass had undercut), and a new
  `SOLAR_MANUFACTURING` at 18 so Premier Energies is not silently valued at the default.

- **Decisions taken under delegated authority** (he asked for the best call and to be told):
  - *Flag 3, capex* — neither option as offered. It fires only on **maintenance** capex; growth
    capex that turns cash flow negative is recorded and routed to flag 7, which is the
    question it actually answers. Information kept, filed where it belongs.
  - *Flags 1–5 in the risk band* — his 0–10 count and bands survive as the **label** he reads;
    the gates use the scores separately so quality is not counted twice in the machinery.
  - *Premier Energies* — a proposed new bottleneck **B1.5 Solar Cell & Module Manufacturing**,
    crossing A1 and A6. His notes treat solar only as a *customer* of transmission and name no
    bottleneck for building the cells.

## Impact

- `investments` — the framework, the structural score, the approval path
- `ui-standards` — the framework panel on the Investments page

Not touched: the ledger, prices, returns, corporate actions, Schedule FA. No model is invoked
anywhere in this stage; the structural score is arithmetic over rows a person agreed with.
