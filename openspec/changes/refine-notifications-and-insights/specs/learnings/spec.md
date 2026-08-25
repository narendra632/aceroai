# learnings Specification

## MODIFIED Requirements

### Requirement: Planned work is never presented as built

The section SHALL distinguish what exists from what is intended. Anything not yet built
SHALL be marked as planned and presented separately from the explanations of working
behaviour.

The same obligation SHALL apply in the opposite direction. An explanation SHALL NOT continue
to describe an implementation the system has superseded, and SHALL NOT describe as absent or
future anything the system has since gained.

This direction is the one that fails silently. A planned feature described as built is
contradicted the moment someone looks for it; a *replaced* implementation still taught as
current looks entirely plausible, and stays wrong until somebody reads the code.

#### Scenario: Something is planned but not built

- **WHEN** the section describes work that has not been done
- **THEN** it is marked as planned and shown apart from what is built

#### Scenario: An implementation has been replaced

- **WHEN** a change replaces how something described in the section works
- **THEN** the explanation is updated to describe the replacement, and the superseded
  mechanism is not left standing as the current one

#### Scenario: Something described as future has since been built

- **WHEN** the section states that some capability is not yet present, and it has since been
  built
- **THEN** that statement is removed or corrected, rather than left to contradict another part
  of the same section
