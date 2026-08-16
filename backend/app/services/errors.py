"""Domain errors raised by services. The REST API maps them to HTTP status codes;
the assistant's tools turn them into structured results the model can recover from.
Keeping them here (not HTTP exceptions) keeps services transport-agnostic.
"""


class NotFound(Exception):
    """A requested record does not exist or does not belong to the user."""


class Invalid(Exception):
    """The requested change is not valid (bad field value, empty content, ...)."""


class Duplicate(Exception):
    """The record would duplicate one that already exists.

    Carries the existing record so the caller can point at it — the assistant should
    say "you already have that one" rather than silently creating a second copy.
    """

    def __init__(self, message: str, existing=None) -> None:
        super().__init__(message)
        self.existing = existing
