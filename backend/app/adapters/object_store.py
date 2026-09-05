"""Durable storage for objects that must outlive the machine.

The only module in this application that imports a cloud storage client. Everything else
depends on `ObjectStore`, which is four methods over bytes, so the backup logic can be
tested exhaustively against an in-memory substitute with no credentials and no network.

**Authentication carries no secret.** In production the VM's attached service account
supplies Application Default Credentials through the GCE metadata server — the same path
that already authenticates Vertex, and the reason adding backups did not add this system's
first long-lived credential on disk. Locally, `gcloud auth application-default login`.

**The client is built lazily and never at import.** CI has no credentials at all, and an
import that reaches for them would fail the collection of every test in the suite, not just
the ones that touch storage.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.config import settings

log = logging.getLogger(__name__)


class ObjectStoreError(RuntimeError):
    """Durable storage could not be reached, or refused.

    One exception type on purpose. A caller's decision is always the same — the backup did
    not happen and the user must be told — and it is never improved by knowing which of a
    vendor's several error classes was raised. The vendor's own message is preserved as the
    cause so an operator loses nothing.
    """


@runtime_checkable
class ObjectStore(Protocol):
    """Somewhere bytes can be put and later got back, addressed by name."""

    def put(self, name: str, data: bytes, *, content_type: str = ...) -> None: ...

    def get(self, name: str) -> bytes: ...

    def list_prefix(self, prefix: str) -> list[str]:
        """Every object name under `prefix`, lexicographically ascending.

        Names are built so that lexical order IS chronological order (see
        `services/backups.object_name`), which is what lets "the newest copy" be the last
        element of a sorted list rather than a metadata query per object.
        """
        ...

    def delete(self, name: str) -> None: ...


class GcsObjectStore:
    """`ObjectStore` backed by a Google Cloud Storage bucket."""

    def __init__(self, bucket: str) -> None:
        self._bucket_name = bucket
        self._bucket = None  # resolved on first use, never at import

    def _resolve(self):
        if self._bucket is None:
            try:
                from google.cloud import storage  # imported here, for the reason above
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise ObjectStoreError("google-cloud-storage is not installed") from exc
            try:
                self._bucket = storage.Client().bucket(self._bucket_name)
            except Exception as exc:
                raise ObjectStoreError(f"cannot reach bucket {self._bucket_name!r}") from exc
        return self._bucket

    def put(
        self, name: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> None:
        try:
            self._resolve().blob(name).upload_from_string(data, content_type=content_type)
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError(f"cannot write {name!r}") from exc

    def get(self, name: str) -> bytes:
        try:
            return self._resolve().blob(name).download_as_bytes()
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError(f"cannot read {name!r}") from exc

    def list_prefix(self, prefix: str) -> list[str]:
        try:
            return sorted(b.name for b in self._resolve().list_blobs(prefix=prefix))
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError(f"cannot list {prefix!r}") from exc

    def delete(self, name: str) -> None:
        try:
            self._resolve().blob(name).delete()
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError(f"cannot delete {name!r}") from exc


def configured_store() -> ObjectStore | None:
    """The bucket this deployment writes to, or None when none is configured.

    None is a first-class answer, not a failure. A developer machine has no bucket, and the
    correct behaviour there is that the backup jobs decline to run and say so — not that
    they fail loudly every night against storage that was never meant to exist.

    Production distinguishes the two: `backup_watch` reports the *absence* of recent
    backups, so a deployment that should have a bucket and does not is caught by the
    silence, rather than by this returning None quietly forever.
    """
    if not settings.backup_bucket:
        return None
    return GcsObjectStore(settings.backup_bucket)
