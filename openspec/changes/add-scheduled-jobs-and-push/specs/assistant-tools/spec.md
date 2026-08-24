# assistant-tools Specification (delta)

## MODIFIED Requirements

### Requirement: The assistant can take actions within a chat turn via tools

Within a single conversation turn, the assistant SHALL be able to call one or more
tools, have the backend execute them against the user's data, and use the results to
form its reply — without the user leaving the chat.

This behavior SHALL live in the shared message handler rather than in any interface that
calls it, so that it is identical for every caller. The handler SHALL remain
channel-agnostic, and SHALL continue to record which channel a conversation took place on,
whether or not more than one channel currently exists.

Automated work that runs on a schedule SHALL NOT invoke this tool loop. Composing a message
for the user without the user present is not the same activity as answering them, and SHALL
NOT carry the ability to take actions.

#### Scenario: A tool call is executed and answered

- **WHEN** the model responds to a message with a tool call rather than text
- **THEN** the backend executes the tool, feeds the result back to the model, and the
  model's final text reply reflects that result

#### Scenario: Behavior belongs to the handler, not the caller

- **WHEN** an actionable request reaches the shared message handler from any caller
- **THEN** the assistant performs the same action through the same service layer

#### Scenario: Scheduled work does not use tools

- **WHEN** the system composes a message on a schedule rather than in response to the user
- **THEN** no tool is available to that composition and no action is taken
