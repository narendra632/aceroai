## ADDED Requirements

### Requirement: The assistant can take actions within a chat turn via tools

Within a single conversation turn, the assistant SHALL be able to call one or more
tools, have the backend execute them against the user's data, and use the results to
form its reply — without the user leaving the chat. This behavior SHALL be identical
across channels (web and Telegram), because it lives in the shared message handler.

#### Scenario: A tool call is executed and answered

- **WHEN** the model responds to a message with a tool call rather than text
- **THEN** the backend executes the tool, feeds the result back to the model, and the
  model's final text reply reflects that result

#### Scenario: Same behavior on every channel

- **WHEN** the same actionable request is sent from web or from Telegram
- **THEN** the assistant performs the same action through the same service layer

### Requirement: Tools operate only on the current user's data

Every tool SHALL act solely on the authenticated user's records. The model MUST NOT be
able to select another user; any record id it supplies MUST be verified to belong to
the current user or the call fails without effect.

#### Scenario: Foreign id is refused

- **WHEN** the model calls a tool with a record id that is not the current user's
- **THEN** the tool call fails safely and nothing is read or changed

### Requirement: The assistant acts on clear requests and confirms risky ones

The assistant SHALL perform single create/update actions when the user's intent is
clear, and SHALL offer rather than silently act when intent is vague. Destructive or
bulk actions (deletions, clearing many items) SHALL require the user's confirmation
before they are carried out.

#### Scenario: Clear request acts immediately

- **WHEN** the user clearly asks to add or update one item
- **THEN** the assistant performs it and reports what it did

#### Scenario: Destructive action confirms first

- **WHEN** the user asks to delete an item or clear many at once
- **THEN** the assistant asks for confirmation before carrying it out

#### Scenario: Vague mention is offered, not forced

- **WHEN** the user only implies a possible task ("I keep forgetting X")
- **THEN** the assistant offers to add it rather than creating it silently

### Requirement: The tool loop is bounded and fault-tolerant

The action loop SHALL be bounded to a maximum number of tool rounds per turn. A
malformed tool call, an unknown id, or a service error SHALL be returned to the model
as a structured result so it can self-correct or explain, and SHALL NOT crash the
chat turn.

#### Scenario: Bounded iterations

- **WHEN** a turn would exceed the maximum number of tool rounds
- **THEN** the loop stops and the assistant responds with what it has

#### Scenario: A failed tool call is recovered

- **WHEN** a tool call is malformed or errors
- **THEN** the failure is reported back to the model and the turn still completes with
  a coherent reply
