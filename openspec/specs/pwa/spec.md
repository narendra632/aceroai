# pwa Specification

## Purpose
TBD - created by archiving change add-scheduled-jobs-and-push. Update Purpose after archive.
## Requirements
### Requirement: The application is installable

The application SHALL describe itself such that a supporting browser can install it to the
device's home screen or application list.

An installed application SHALL open in its own window without browser navigation furniture,
SHALL carry its own name and icon, and SHALL present colours consistent with the user's
chosen theme.

#### Scenario: Installing

- **WHEN** the user chooses to install the application from a supporting browser
- **THEN** it is added to the device with its own name and icon

#### Scenario: Opening the installed application

- **WHEN** the user opens the installed application
- **THEN** it fills the window without browser navigation controls and matches the current
  theme

### Requirement: Installation is offered where possible and explained where it is not

The application SHALL offer installation when the browser signals that it is available.

Where a platform does not offer an installation prompt, the application SHALL detect that
situation and describe how to install manually, rather than offering nothing.

The offer SHALL NOT appear when the application is already running as installed.

#### Scenario: The browser offers installation

- **WHEN** the browser indicates the application can be installed
- **THEN** the application presents a way to install it

#### Scenario: A platform without a prompt

- **WHEN** the platform provides no installation prompt
- **THEN** the application explains the manual steps for that platform

#### Scenario: Already installed

- **WHEN** the application is already running as an installed application
- **THEN** no installation offer is shown

### Requirement: Losing the connection is reported, never disguised

When the device has no connection, the application SHALL load and SHALL state clearly that it
is offline.

Areas that require data SHALL show an offline state rather than an indefinite loading state or
an empty result that reads as "you have nothing".

The application SHALL recover without a manual reload when connectivity returns.

#### Scenario: Opening while offline

- **WHEN** the user opens the installed application with no connection
- **THEN** it loads and states that it is offline

#### Scenario: Offline is not emptiness

- **WHEN** a view cannot load its data because the device is offline
- **THEN** it says the device is offline, rather than showing a spinner indefinitely or an
  empty list

#### Scenario: Coming back

- **WHEN** connectivity returns
- **THEN** the application recovers without the user reloading it

### Requirement: The user's data is never served from a stale cache

Responses containing the user's data SHALL NOT be cached by the installed application.

Only the application's own program files SHALL be cached, and a newly deployed version SHALL
take effect without the user clearing anything.

#### Scenario: Data is always current

- **WHEN** the user views their data in the installed application
- **THEN** it reflects the server's current state and not a previously cached response

#### Scenario: A new version is deployed

- **WHEN** a new version of the application is deployed
- **THEN** the installed application picks it up without the user clearing storage or
  reinstalling

### Requirement: A background surface exists to receive notifications

The application SHALL maintain a background component capable of receiving and presenting
notifications while the application itself is not open.

Selecting a delivered notification SHALL bring the application to the relevant place, reusing
an already-open window where one exists rather than opening another.

#### Scenario: Notified while closed

- **WHEN** a notification arrives and the application is not open
- **THEN** it is presented on the device

#### Scenario: Opening from a notification

- **WHEN** the user selects a delivered notification
- **THEN** the application opens at what the notification is about

#### Scenario: Already open

- **WHEN** the user selects a notification while the application is already open
- **THEN** the existing window is focused and navigated, rather than a second one opening

