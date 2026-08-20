# documentation Specification

## Purpose
How the system explains itself: the documents that describe what was
built, why it was built that way, and how to run it — kept true to the code
rather than to the plan.

## Requirements
### Requirement: Documentation describes the system as built

Every document in the repository SHALL describe behavior that is actually implemented, so
that a reader — human or agent — who trusts the documentation is not misled into building
against a system that no longer exists.

#### Scenario: A document contradicts the code

- **WHEN** a document states behavior that the code does not implement
- **THEN** that statement is a defect and is corrected, not annotated or appended to

#### Scenario: A referenced path, command, or setting does not exist

- **WHEN** a document names a file path, a command, or a configuration setting
- **THEN** that path, command, or setting exists as written and is verified before the
  change is considered done

#### Scenario: Planned work is described

- **WHEN** work is planned but not yet implemented
- **THEN** it is recorded in the roadmap, and NOT written into the architecture
  documentation as though it were part of the system

### Requirement: Each document has a single job

Documentation SHALL be organized so that each file answers one question, so that a change
has exactly one correct place to land and cannot be recorded by appending to whichever
file is open.

#### Scenario: Current status changes

- **WHEN** a feature ships and the project's status changes
- **THEN** the roadmap is updated, and the architecture document — which describes how the
  system works, not where the project stands — is updated only if the mechanism changed

#### Scenario: The same fact appears in two documents

- **WHEN** a fact would need to be stated in more than one document
- **THEN** one document owns it and the others link to it, so the fact cannot be updated
  in one place and left stale in another

### Requirement: Architecture is expressed in diagrams that live in version control

The system's structure and its principal flows SHALL be documented as diagrams stored as
**text in the repository**, so that a diagram change can be reviewed in a diff and edited
without specialized tooling.

#### Scenario: The architecture changes

- **WHEN** a component is added, removed, or re-wired
- **THEN** the affected diagrams are updated in the same change as the code

#### Scenario: A reader wants to see a diagram

- **WHEN** a reader opens the documentation on the code host or in an editor
- **THEN** the diagrams render without installing a plugin, running a build step, or
  exporting an image

#### Scenario: A diagram change is reviewed

- **WHEN** a diagram is modified
- **THEN** the diff shows what changed in the system in readable terms, rather than
  changes to layout geometry

#### Scenario: A diagram states a measured figure

- **WHEN** a diagram includes a latency, cost, or size figure
- **THEN** that figure comes from a recorded measurement, and the diagram and the
  measurement record cannot disagree

### Requirement: Documentation is updated by the change that alters the behavior

Keeping documentation true SHALL be part of completing a change, so that accuracy does not
depend on remembering to revisit it afterwards.

#### Scenario: A change alters behavior a document describes

- **WHEN** a change is prepared through the OpenSpec workflow
- **THEN** its task list contains an explicit item confirming that documentation and
  diagrams reflect what was built, checked in the same way tests are

#### Scenario: A change alters no documented behavior

- **WHEN** a change genuinely affects nothing that is documented
- **THEN** that item is answered explicitly rather than silently skipped, so the
  distinction between "checked" and "forgotten" stays visible
