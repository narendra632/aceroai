# investments — the framework as versioned data

## ADDED Requirements

### Requirement: The investment framework is stored data, not logic in the code

The system SHALL hold the framework — the imperatives, the bottlenecks, what each bottleneck
blocks, and the fair multiple for each sector — as versioned records. A change to any of it
SHALL create a new version rather than altering the existing one, and every score and every
proposal SHALL record the version that produced it.

⚠ This is what makes improving the framework safe. A score made in one month must remain
explainable in another, which is impossible if the rules it used were re-derived each time
from whatever the code says today.

#### Scenario: The framework is changed

- **WHEN** the framework's contents are edited
- **THEN** a new version is created, the previous one remains readable, and anything already
  scored still points at the version that produced it

#### Scenario: The framework has not been installed

- **WHEN** something asks for a score and no approved framework exists
- **THEN** the request is refused with that reason, and no score is estimated

### Requirement: A claim that a company serves a national bottleneck scores nothing until a person agrees

The system MAY propose that a company clears a particular bottleneck, and SHALL record the
reasoning for that proposal. The proposal SHALL contribute **zero** to any structural score
until a human approves it.

Replacing a company's mapping SHALL create a new proposal that supersedes the old one and is
itself unapproved.

⚠ Without this, a system that reads enough news will eventually narrate an unrelated company
into national importance, and nothing in the score can tell that apart from the real thing.
A re-mapping does not inherit the agreement given to the mapping it replaced, because it is a
different claim.

#### Scenario: The system proposes a mapping

- **WHEN** a company is proposed as clearing a bottleneck
- **THEN** its structural score is zero, the interface says the mapping is awaiting agreement,
  and approving it is what allows the company to score

#### Scenario: A company is moved to a different bottleneck

- **WHEN** an approved mapping is replaced
- **THEN** the replacement is unapproved, the company scores zero until it is confirmed, and
  the superseded mapping can no longer be approved

### Requirement: A framework judgement expires rather than standing for ever

An approved mapping SHALL carry a date after which it is raised for re-confirmation.

⚠ A mapping states what a company does *today*. A business that changes what it does — a
contract manufacturer moving into semiconductor packaging — would otherwise continue to be
scored against the business it used to be, with nothing anywhere reporting it.

#### Scenario: A mapping passes its review date

- **WHEN** an approved mapping is older than its review period
- **THEN** it appears in the list of things needing a person, asking whether the company still
  does what it did when the mapping was agreed

### Requirement: A gap in the framework is reported as a gap, never scored as a finding

Where the framework does not establish how many imperatives a bottleneck blocks, the system
SHALL record what is known as a **floor** and SHALL mark it as such. It SHALL NOT substitute a
default value that would be indistinguishable from an established one.

Where a company's sector has no fair multiple, the system SHALL say so wherever a figure
derived from that multiple is shown, rather than silently applying a default.

⚠ Both are the same failure: a value that is missing, replaced by one that looks measured. A
company would score narrow because a section of the source material is brief, or appear to
have a computed margin of safety that was in fact guessed — and nothing would prompt anyone to
correct either.

#### Scenario: A bottleneck whose breadth was never established

- **WHEN** a company is scored against such a bottleneck
- **THEN** the score uses the known floor, and the interface states that the figure is a
  floor and may be understated

#### Scenario: A company in a sector with no fair multiple

- **WHEN** that company is valued
- **THEN** the default multiple is used and the interface says it was the default, so any
  margin of safety derived from it is visibly a guess

### Requirement: A company outside the framework is distinguished from one that scores badly

Where the framework does not apply to a company, the system SHALL report the structural score
as **unavailable with a reason**, and SHALL NOT report it as zero.

⚠ These are different answers. Zero means "measured against this framework and found
wanting". Unavailable means "this framework does not ask a question about this company" — the
honest verdict on a foreign holding, since the framework asks what India must build.

#### Scenario: A foreign holding

- **WHEN** a company in another country's market is scored
- **THEN** no structural score is produced, the reason is stated, and the holding is still
  tracked, valued and reported

#### Scenario: A holding the user has declared off-thesis

- **WHEN** the user marks a company as outside the framework
- **THEN** it is scored the same way as a foreign holding, and limits on off-framework
  exposure govern what may be added rather than retrospectively blocking what is held

### Requirement: Companies that are watched but not held are scored

The system SHALL score any tracked company against the framework, whether or not it is held,
and SHALL distinguish the two in the interface.

⚠ Without this the system can only ever say "hold" or "sell". Identifying what deserves
attention is the framework's purpose, and it has nothing to identify if it can only see what
has already been bought.

#### Scenario: A watchlist company

- **WHEN** a company with no transactions is tracked
- **THEN** it is scored, shown as watched rather than held, and never appears as a holding or
  affects any return
