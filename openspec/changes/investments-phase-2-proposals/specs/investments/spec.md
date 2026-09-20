# investments — proposals, and the rules that refuse them

## ADDED Requirements

### Requirement: The system proposes and never acts

The system SHALL NOT place an order, connect to any brokerage, or alter the user's real
holdings. An approved suggestion SHALL update only the system's own paper book.

What the user does in the real world SHALL be recorded the same way every other transaction
is — by the user — and the two books SHALL remain separate.

⚠ This is not a limitation to engineer away later. It is what keeps the system outside the
regulatory category governing automated trading, and the difference between the two books is
one of the most interesting measurements the module produces.

#### Scenario: A suggestion is approved

- **WHEN** the user approves a suggestion
- **THEN** the system's own paper book records it, the real book is untouched, and no order
  exists anywhere

### Requirement: A suggestion is recorded with everything that produced it, frozen

Every suggestion SHALL record, at the moment it is made: the price the system saw, the scores
it rested on, which rules were checked and what each decided, the version of the framework in
force, and references to the records its figures came from.

None of these SHALL be recomputed when the suggestion is later read.

⚠ What the system SAW is a different fact from what the market DID. A review that recomputes
the inputs is reconstructing a decision rather than examining one, and the difference is
invisible from the outside.

#### Scenario: A suggestion is reviewed months later

- **WHEN** an old suggestion is read
- **THEN** the price, the scores and the rule results are those recorded at the time, not
  today's

### Requirement: A suggestion cannot be made without stating what would prove it wrong

Every suggestion to buy SHALL carry at least two invalidation conditions, each expressed as a
metric, a comparison, a threshold and a deadline. Conditions expressed only in prose SHALL be
refused.

⚠ "If the story changes" cannot be checked, so a position carrying it can never be shown to
have been wrong — which is the same as carrying no condition at all, dressed as caution.

#### Scenario: A suggestion with only narrative conditions

- **WHEN** its invalidation conditions cannot be evaluated mechanically
- **THEN** the suggestion is refused and the refusal names that rule

### Requirement: The rules that refuse a suggestion are applied by code, not by instruction

The conditions under which a suggestion may not be made SHALL be evaluated in program code
against stored records. The system SHALL NOT rely on a language model being instructed to
respect them.

The result of every rule SHALL be recorded, distinguishing a rule that passed from one that
did not apply.

⚠ A rule that a sufficiently persuasive argument can talk its way past is a preference. The
reason for writing rules down before anything is at stake is that they bind on the day you
would rather they did not — and "not asked" counted as "satisfied" would overstate how much
was ever checked.

#### Scenario: A company whose business is poor and whose story is loud

- **WHEN** it is considered for purchase
- **THEN** it is refused regardless of how strong the argument for it reads

#### Scenario: A sale considered against rules about buying

- **WHEN** the rules are applied
- **THEN** the buying rules are recorded as not applicable rather than as passed

### Requirement: A refused suggestion is recorded as carefully as an accepted one

Where a rule refuses a suggestion, the system SHALL still record the suggestion, the rule that
refused it, and an entry in a separate book tracking what did not happen.

⚠ A rule whose cost is invisible is a rule nobody can evaluate. Only the record of what the
rules refused can ever answer whether they are protecting or merely obstructing.

#### Scenario: A rule blocks a purchase

- **THEN** the suggestion is stored with the blocking rule named, it is never offered for a
  decision, and it appears in the book of what the rules refused

### Requirement: Every decision carries a reason in the user's own words

The system SHALL require a reason with every approval, rejection or modification, and SHALL
refuse a decision without one.

⚠ The reason is the data that eventually reveals what kinds of suggestion keep being turned
down. It is the only route by which the system learns anything about its own judgement; a
decision without one records that something happened and nothing about why.

#### Scenario: A decision is submitted with no reason

- **THEN** it is refused, and nothing is recorded

### Requirement: A suggestion lapses rather than standing indefinitely

A suggestion not acted on within a defined period SHALL be treated as lapsed and SHALL NOT be
actionable.

⚠ A suggestion was made at a price. Weeks later that price is history, and acting on it is
acting on a judgement about a world that has moved.

#### Scenario: An old suggestion

- **WHEN** the user tries to act on a suggestion past its validity
- **THEN** the attempt is refused with that reason

### Requirement: Every thinking run is recorded, including the ones that suggest nothing

The system SHALL record each run of the deciding job with what it considered and what it
produced, whether or not it produced anything.

⚠ Suggesting nothing is a normal and frequently correct outcome. A system that only leaves a
trace on the days it acted can never be measured against the days it should have acted and did
not — the record becomes a highlight reel.

#### Scenario: An evening with nothing worth suggesting

- **THEN** a run is recorded showing what was considered and that nothing was produced, and
  the user is not notified

#### Scenario: The same run happens twice

- **WHEN** a scheduled run repeats for an occurrence already recorded
- **THEN** no second set of suggestions is written
