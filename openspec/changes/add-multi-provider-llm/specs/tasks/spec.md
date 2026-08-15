## ADDED Requirements

### Requirement: Creating a task that duplicates an open one is refused

Creating a task SHALL be refused when an open task with an equivalent title already
exists, and the refusal SHALL identify the existing task so the caller can point at it
or update it. Equivalence ignores differences in case, punctuation and spacing.
Callers that genuinely want a second copy MAY override this explicitly.

#### Scenario: An equivalent open task blocks creation

- **WHEN** a task is created whose title matches an open task apart from case,
  punctuation or spacing
- **THEN** creation is refused, the existing task is identified, and no second task is
  stored

#### Scenario: Differently worded work is still allowed

- **WHEN** a task is created whose title is worded differently from every open task
- **THEN** it is created normally

#### Scenario: Completed work does not block new work

- **WHEN** a task is created with the same title as a task that is already done
- **THEN** it is created normally, so recurring work is possible

#### Scenario: A duplicate can be forced deliberately

- **WHEN** a caller explicitly allows duplicates
- **THEN** the task is created even though an equivalent open task exists
