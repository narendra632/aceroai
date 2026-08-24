# learnings Specification (delta)

## MODIFIED Requirements

### Requirement: The system explains itself inside the product

The application SHALL provide a section that explains how it works, reachable from the main
navigation like any other part of the product.

It SHALL cover, at minimum: the path a message takes from being sent to being answered; how
cost and activity are recorded; **how the system acts on its own — what runs on a schedule,
what decides whether to tell the user something, and how it reaches them when the application
is closed**; and the general concepts the implementation rests on.

#### Scenario: Reaching the explanation

- **WHEN** the user opens the application
- **THEN** the section explaining the system is reachable from the main navigation

#### Scenario: The message path is explained

- **WHEN** the user opens the section
- **THEN** it presents the stages a message passes through, in the order they happen

#### Scenario: Acting without being asked is explained

- **WHEN** the user opens the section
- **THEN** it presents how scheduled work runs and how a notification reaches the user's
  device, in the order those stages happen
