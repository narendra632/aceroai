# ui-standards Specification

## MODIFIED Requirements

### Requirement: Stored data is visible and editable by its owner

Anything the data model records about the user SHALL be viewable and correctable through
the interface, so that no information exists in the system that its owner cannot see or
change.

Where a record is deliberately append-only, correction SHALL still be offered from the
interface, expressed as a superseding entry rather than a modification. Both the original and
the entry that supersedes it SHALL remain visible, and the interface SHALL describe the action
truthfully rather than borrowing the wording of an edit or a deletion.

This is an exception to *how* a correction is made, never to *whether* one is available. A
record the user cannot correct is the defect this requirement exists to prevent; a record that
keeps its own history of corrections is not that. The exception has to be earned by the
record's purpose — the investments ledger exists to be judged against months later, and a row
that can be quietly rewritten cannot judge anyone.

#### Scenario: A record is created with a mistake

- **WHEN** the user has created a record and needs to correct it
- **THEN** every field the record stores can be edited — correcting a mistake never
  requires deleting and re-creating

#### Scenario: A mistake in an append-only record

- **WHEN** the user needs to correct a record the system does not permit editing
- **THEN** the interface offers the correction, records it as a superseding entry, keeps both
  entries visible, and says that the original remains in the record

#### Scenario: The assistant writes a field

- **WHEN** the assistant sets a value on the user's data through its tools
- **THEN** that value is visible in the interface and editable there — the assistant
  cannot write data the user has no way to see
