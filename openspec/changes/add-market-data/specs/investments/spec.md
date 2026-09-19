# investments — market data

## ADDED Requirements

### Requirement: Prices arrive without being typed

The system SHALL obtain prices for held instruments from external sources on a schedule: a
daily close (or NAV) for every holding, and a live price during market hours for holdings
that trade intraday. Fetched prices SHALL be recorded as observations in the same form as a
typed price, differing only in their source.

A daily close SHALL come from a source that does not depend on a broker login, so that the
close of record survives the broker's API being unavailable.

#### Scenario: The evening after a trading day

- **WHEN** the scheduled close run completes on a trading day
- **THEN** every held NSE equity has a close observation for that day, recorded with the
  exchange's file as its source

#### Scenario: The broker API is down

- **WHEN** the live-price source cannot be reached
- **THEN** no error reaches the user; the last price is shown with its age and marked stale
  once past its limit, and the next day's close still arrives from the exchange's file

### Requirement: History fills itself

Every scheduled price run SHALL fill every missing day between a holding's first trade (or the
earliest day its source provides) and today. There SHALL be no separate backfill step that
must be remembered on a new or restored database.

Filling SHALL be idempotent: running it again over days already filled SHALL write nothing.

#### Scenario: A fresh database

- **WHEN** the first price run executes against a book with months of trades and no prices
- **THEN** it records a close for every trading day the sources provide, and the value line
  appears for every day on which every open holding has one

#### Scenario: A repeated run

- **WHEN** a price run executes twice over the same days
- **THEN** the second writes no new observations

#### Scenario: A source's history is shorter than the holding

- **WHEN** a holding was bought before the earliest day its source provides
- **THEN** history is filled from that earliest day, and the value line is absent before it
  rather than estimated

### Requirement: Live prices are fetched only when stale

When the portfolio is viewed — on the page or through the assistant — the system SHALL fetch a
fresh price only for holdings whose newest price is missing or older than the staleness limit
for their kind. Both callers SHALL use the same service function.

#### Scenario: Opening the page after the close

- **WHEN** the page is opened in the evening and each holding already has today's close
- **THEN** no external price request is made

### Requirement: The market-data connection cannot trade

The broker integration SHALL be capable only of logging in and reading prices. It SHALL NOT
contain the addresses of any order, holdings, positions or trigger endpoint, so no defect or
misuse can place or inspect a trade through it.

#### Scenario: The adapter is inspected

- **WHEN** the broker adapter's source is examined by the test suite
- **THEN** it names exactly the login, quote and candle routes and no others

### Requirement: Corporate actions on held stocks are announced before they distort value

The system SHALL watch the exchange's corporate-action feed and notify the user of any split,
bonus or consolidation announced for a held stock, once per action. It SHALL NOT record the
action in the ledger itself.

#### Scenario: A bonus is announced for a held stock

- **WHEN** the feed lists a bonus issue for a company whose stock is held
- **THEN** the user is notified once, naming the stock, the action and its ex-date

#### Scenario: A dividend is announced

- **WHEN** the feed lists only a dividend for a held stock
- **THEN** no notification is raised
