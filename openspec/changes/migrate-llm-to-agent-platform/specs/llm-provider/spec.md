## ADDED Requirements

### Requirement: The app reaches the model provider through configuration alone

The provider endpoint, credentials mode, and model identifiers SHALL be configuration,
not code. Switching between the supported providers SHALL require only configuration
changes and a restart.

#### Scenario: Switching providers

- **WHEN** the configured provider is changed and the app restarts
- **THEN** requests go to that provider's endpoint with its credentials and model
  identifiers, and no application code changes are required

#### Scenario: Rolling back a provider migration

- **WHEN** the newly configured provider is failing
- **THEN** restoring the previous provider configuration returns the app to working
  order without redeploying different code

### Requirement: Credential-based authentication refreshes without restarts

When the provider requires short-lived credentials, the app SHALL obtain them from the
environment's ambient credentials and SHALL refresh them before they expire, so a
long-running server keeps working without a restart or manual rotation. In production
this MUST NOT require a static provider key stored in application config.

#### Scenario: Expired credential is refreshed

- **WHEN** a request is made after the current credential has expired or is about to
- **THEN** a fresh credential is obtained automatically and the request succeeds

#### Scenario: No static key in production

- **WHEN** the app runs in production against a credential-based provider
- **THEN** it authenticates from the environment's identity without a provider API key
  in its configuration

### Requirement: Existing model behavior is preserved across providers

After a provider change, streaming replies, assistant tool-calling, and semantic memory
recall SHALL continue to behave as before from the user's point of view.

#### Scenario: Streaming still streams

- **WHEN** a user sends a normal chat message
- **THEN** the reply streams incrementally as it did before the provider change

#### Scenario: Tools still work

- **WHEN** a user asks the assistant to create a task or log a journal entry
- **THEN** the assistant performs the action through its tools and confirms it

#### Scenario: Memory still recalls

- **WHEN** a message is sent that relates to a known fact about the user
- **THEN** relevant facts are still recalled into context, or recall degrades silently
  without blocking the reply

### Requirement: Provider failures are reported honestly

A provider rejection SHALL be surfaced to the user in terms that match its cause: a
genuine rate limit MUST be described as a rate limit, while a billing or quota
rejection MUST NOT be described as a rate limit. Provider internals MUST NOT be leaked
to the client.

#### Scenario: Billing rejection is not called a rate limit

- **WHEN** the provider rejects a request because of billing or exhausted quota
- **THEN** the user-facing message indicates a provider/billing problem rather than a
  temporary rate limit

#### Scenario: Internal detail is not leaked

- **WHEN** any provider error occurs
- **THEN** the user-facing message contains no raw provider error text, while the full
  detail is logged server-side
