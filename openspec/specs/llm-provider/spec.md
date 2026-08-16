# llm-provider Specification

## Purpose
TBD - created by archiving change add-multi-provider-llm. Update Purpose after archive.
## Requirements
### Requirement: The app supports multiple model providers through one internal interface

The app SHALL reach every supported model provider through a single internal interface,
so that chat streaming, assistant tool-calling, and embeddings behave identically to the
rest of the system regardless of which provider serves a request.

#### Scenario: Streaming behaves the same on any provider

- **WHEN** a user sends a normal chat message on any supported provider
- **THEN** the reply streams incrementally, as it does on every other provider

#### Scenario: Multi-turn tool calling works on any provider

- **WHEN** the assistant needs more than one tool round to answer (for example, look up
  tasks and then update one)
- **THEN** the sequence completes successfully on any supported provider, and the
  assistant reports the result

#### Scenario: Adding a provider does not change callers

- **WHEN** a new provider implementation is added behind the interface
- **THEN** the message handler, tool loop, memory, and channel adapters require no
  changes

### Requirement: Each provider is used through its native interface

Every provider SHALL be integrated through its own first-class API rather than a
compatibility shim, so that no provider's capabilities are degraded and
provider-specific behavior required for correctness is preserved.

#### Scenario: Provider-specific tool metadata is preserved

- **WHEN** a provider requires metadata from a tool call to be returned on the following
  turn
- **THEN** that metadata is carried back and the multi-turn exchange succeeds

#### Scenario: Unsupported options are not silently discarded

- **WHEN** a request option cannot be honored by the selected provider
- **THEN** the app does not silently send a request that ignores it; the option is
  mapped to that provider's equivalent or omitted deliberately

### Requirement: The user selects the provider and models from the app

A user SHALL be able to view and change their preferred provider, their normal chat
model, and their deeper-reasoning model from within the app, and the selection SHALL
persist and apply to their subsequent conversations on every channel.

#### Scenario: Changing the provider takes effect

- **WHEN** a user changes their provider or model in settings and then sends a message
- **THEN** the reply is produced by the newly selected provider and model

#### Scenario: The selection applies to other channels

- **WHEN** a user has chosen a provider in the app and then messages the assistant from
  another channel
- **THEN** that same provider and model are used

#### Scenario: Unset preferences fall back to defaults

- **WHEN** a user has never chosen a provider or model
- **THEN** the server's configured defaults are used

#### Scenario: Settings are per user

- **WHEN** a user reads or updates settings
- **THEN** only that user's settings are read or changed

### Requirement: Only providers with configured credentials are offered

The app SHALL offer only those providers whose credentials are configured on the server,
and SHALL reject a selection of any provider that is not available. Provider credentials
MUST NOT be entered, displayed, or stored through the user interface.

#### Scenario: Unavailable provider is not offered

- **WHEN** a provider has no credentials configured on the server
- **THEN** it is not presented as a selectable option

#### Scenario: Selecting an unavailable provider is rejected

- **WHEN** a request sets the provider to one that is unavailable
- **THEN** the request is rejected and the stored preference is unchanged

#### Scenario: No credentials in the interface

- **WHEN** a user views settings
- **THEN** no provider API key or secret is shown, and none can be submitted

### Requirement: Embeddings stay pinned so stored memory remains valid

The embedding model used for semantic memory SHALL be configured independently of the
user's chat provider selection, and changing the chat provider MUST NOT change which
embedding model produces vectors. The embedding dimension MUST continue to match the
stored vectors.

#### Scenario: Switching chat provider does not change embeddings

- **WHEN** a user switches their chat provider
- **THEN** memory embeddings continue to be produced by the pinned embedding model, and
  previously stored facts remain recallable

#### Scenario: Recall still works after switching

- **WHEN** a user sends a message related to a fact learned before the switch
- **THEN** that fact can still be recalled into context

#### Scenario: The pinned embedding model is visible but not casually changeable

- **WHEN** a user views settings
- **THEN** the embedding model in use is shown as fixed, together with an explanation
  that changing it would invalidate stored memory and requires re-embedding every
  stored fact — it is not offered as an ordinary selectable option

### Requirement: Provider failures are reported honestly

A provider rejection SHALL be described to the user according to its cause: a genuine
rate limit MUST be described as a rate limit, while a billing or quota problem MUST NOT
be described as a rate limit. Raw provider error detail MUST NOT reach the client.

#### Scenario: Billing rejection is not called a rate limit

- **WHEN** the provider rejects a request because of billing or exhausted quota
- **THEN** the user-facing message points to a provider/billing problem rather than a
  temporary rate limit

#### Scenario: Internal detail is not leaked

- **WHEN** any provider error occurs
- **THEN** the user-facing message contains no raw provider error text, while full
  detail is logged server-side

