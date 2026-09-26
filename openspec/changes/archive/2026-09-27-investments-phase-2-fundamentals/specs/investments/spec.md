# investments — filed numbers and what they say

## ADDED Requirements

### Requirement: Company figures come from filings, stored with the text they were filed as

The system SHALL obtain a company's reported figures from its own regulatory filings, and
SHALL store, alongside each figure, the literal text it was extracted from.

The system SHALL NOT store the filing document itself.

⚠ The text is what makes the rule that a model never produces a number enforceable: a figure in
a thesis can be checked back, character by character, against what the company submitted. A
validator given only the parsed number would be comparing a number with itself.

#### Scenario: A figure is used in an argument

- **WHEN** any figure about a company is presented
- **THEN** it can be traced to the filing it came from and to the words in that filing

#### Scenario: A company restates a year

- **WHEN** the same period is reported again in a later filing
- **THEN** the later statement is the one readers receive, and the earlier one remains recorded

### Requirement: A figure that describes one period is never read as another

The system SHALL resolve each reported figure to the period it describes, using that period's
dates, and SHALL NOT rely on labels or on ordering within the document.

Figures qualified by a business segment or other breakdown SHALL NOT be read as the company's.

⚠ An annual filing reports the same measure for the final quarter and for the whole year under
an identical tag. Reading the wrong one is wrong by roughly four, silently, on every ratio
derived from it — and nothing downstream could detect it.

#### Scenario: An annual filing carrying both a quarter and a year

- **WHEN** figures are extracted from it
- **THEN** the yearly figure and the quarterly figure are stored as distinct periods

#### Scenario: A filing reporting revenue by segment

- **WHEN** figures are extracted
- **THEN** no segment's figure is recorded as the company's own

### Requirement: A company that reports on one basis only is still read

Where a company reports both a consolidated and a standalone statement, the system SHALL use
the consolidated one. Where only one basis exists, the system SHALL use it, and SHALL record
which basis every figure came from. The system SHALL NOT mix bases within a series.

⚠ A company with no subsidiaries files no consolidated statement. Requiring one leaves such a
company with no financial history at all, and the failure reads as though the company does not
report.

#### Scenario: A company with no subsidiaries

- **WHEN** its filings are read
- **THEN** its standalone statements are used, and each figure records that basis

### Requirement: Business quality is scored from filed figures alone, and says what it could not measure

The system SHALL score a company's business quality and the reasonableness of its price using
only figures from filings and observed prices, computing every ratio in ordinary code.

A component whose inputs are absent SHALL be reported as **unmeasured**, never as zero. The
score SHALL be reported as points earned against points **available**, and the unmeasured
components SHALL be named.

A component requiring several years SHALL decline to answer where too few years have been read.

#### Scenario: A company whose filings have not been read

- **WHEN** it is scored
- **THEN** every component reports unmeasured, nothing is scored zero, and the interface can
  name what is missing

#### Scenario: A single year against a multi-year test

- **WHEN** a test asks about several years and one has been read
- **THEN** the component reports unmeasured and states how many years it had

### Requirement: A company is not judged on arithmetic that does not describe it

Where a measure does not apply to a company's kind of business, the system SHALL report that
measure as unmeasured rather than scoring it.

⚠ Borrowings are a lender's raw material rather than its leverage, and its cash flows follow
deposits rather than trading. Scoring those as though they described an industrial classifies
a sound lender as a failing business — and that classification blocks any further purchase.

#### Scenario: A lender scored on leverage

- **WHEN** a company whose business is lending is scored
- **THEN** leverage, cash conversion and return on capital report unmeasured, and the measures
  that do describe it are scored normally

### Requirement: A verdict that blocks a purchase is refused on a partial reading

Where the system classifies a company into a category that forbids buying it, it SHALL first
require that enough of the score was measurable, including the company's price.

⚠ A company blocked because its accounts have not been read is indistinguishable from one
blocked because it deserves to be, and only one of those is a judgement.

#### Scenario: Few components could be measured

- **WHEN** a company is classified
- **THEN** no category that blocks a purchase is assigned, and the classification states that
  the reading was too thin to judge

#### Scenario: The company's price is unknown

- **WHEN** a company has no observed price
- **THEN** no blocking category is assigned, because price is half of the question

### Requirement: A checklist question with no evidence is answered unknown

Where a checklist question can be computed from filings or prices, the system SHALL compute it
and SHALL record that it was computed. Where the inputs are absent, the answer SHALL be
**unknown** rather than a default. A computed answer SHALL NOT be overridden by a judgement.

⚠ A checklist that answers "no" by default reports a clean bill of health it never checked.

#### Scenario: No price history exists

- **WHEN** a question about the price range is asked
- **THEN** the answer is unknown, with the reason, rather than "no"
