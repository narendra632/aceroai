# auth Specification

## Purpose
TBD - created by archiving change add-web-chat. Update Purpose after archive.
## Requirements
### Requirement: Email/password login issues a session cookie

The system SHALL authenticate a user from an email and password and, on
success, issue a JWT in an httpOnly cookie. Passwords MUST be verified against
the stored bcrypt hash; the plaintext password MUST NOT be logged or returned.

#### Scenario: Successful login

- **WHEN** a client POSTs valid credentials to `/api/auth/login`
- **THEN** the response sets an httpOnly cookie containing a signed JWT whose
  subject is the user id, and returns the user's email

#### Scenario: Wrong password

- **WHEN** a client POSTs a known email with an incorrect password
- **THEN** the system responds `401` and sets no cookie

#### Scenario: Unknown email

- **WHEN** a client POSTs an email that does not exist
- **THEN** the system responds `401` without revealing whether the email exists

### Requirement: Protected routes require a valid session

The system SHALL expose a `get_current_user` dependency that resolves the
authenticated user from the request cookie and MUST reject requests whose cookie
is missing, malformed, expired, or has an invalid signature.

#### Scenario: Missing cookie

- **WHEN** a request to a protected route arrives with no auth cookie
- **THEN** the system responds `401` and does not run the route handler

#### Scenario: Valid cookie

- **WHEN** a request to a protected route carries a valid, unexpired auth cookie
- **THEN** the dependency loads the matching user and the route proceeds

### Requirement: Session check and logout

The system SHALL provide a way to check the current session and to end it.

#### Scenario: Who am I

- **WHEN** an authenticated client GETs `/api/auth/me`
- **THEN** the system returns the current user's email

#### Scenario: Logout clears the cookie

- **WHEN** a client POSTs to `/api/auth/logout`
- **THEN** the system clears the auth cookie so subsequent protected requests
  respond `401`

