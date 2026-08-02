## ADDED Requirements

### Requirement: The backend is served over HTTPS in production

In production the API SHALL be reachable only over HTTPS, terminated by a reverse
proxy that obtains and renews certificates automatically. Internal services (the
API process and the database) MUST NOT be publicly exposed.

#### Scenario: HTTPS endpoint responds

- **WHEN** the deployed backend's health endpoint is requested over HTTPS
- **THEN** it responds successfully with a valid certificate

#### Scenario: Database is not public

- **WHEN** the deployment is running
- **THEN** the database port is not published to the public internet; only the
  reverse proxy's HTTP/HTTPS ports are

### Requirement: The auth cookie is production-safe and cross-site capable

When configured for production, the login cookie SHALL be set `Secure` and with a
`SameSite` value that allows it to be sent from the configured frontend origin to
the backend. In development the defaults SHALL remain a non-secure, `Lax` cookie.

#### Scenario: Production cookie attributes

- **WHEN** the app is configured for production and a user logs in
- **THEN** the auth cookie is set `Secure` with the configured `SameSite` value

#### Scenario: Development cookie attributes

- **WHEN** the app runs with development defaults and a user logs in
- **THEN** the auth cookie is set non-secure with `SameSite=Lax`

### Requirement: The app refuses to start insecurely in production

On startup in production, the app SHALL refuse to run if the JWT signing secret is
still the built-in development default.

#### Scenario: Default secret in production

- **WHEN** the app starts with a production environment and the default JWT secret
- **THEN** startup fails with a clear error and the app does not serve requests

#### Scenario: Real secret in production

- **WHEN** the app starts in production with a non-default JWT secret
- **THEN** the app starts normally

### Requirement: CORS is restricted to the configured frontend origin

The API SHALL accept browser cross-origin requests (with credentials) only from the
configured frontend origin.

#### Scenario: Only the configured origin is allowed

- **WHEN** a browser request arrives from an origin other than the configured
  frontend origin
- **THEN** the response does not grant cross-origin access to that origin

### Requirement: The production runtime uses the real persona

The deployed backend SHALL load the real `SOUL.md` persona rather than the fallback
stub, via a configurable path that the deployment provides.

#### Scenario: Persona available in production

- **WHEN** context is built in the deployed backend
- **THEN** the system message is the real SOUL.md persona, not the fallback stub

### Requirement: Changes to main are built and deployed automatically

After the manual bring-up, a push to `main` that passes CI SHALL build the backend
image and deploy it to the running host without manual steps.

#### Scenario: Push deploys

- **WHEN** a commit that passes CI lands on `main`
- **THEN** the backend image is built, published, and the host is updated to run it
