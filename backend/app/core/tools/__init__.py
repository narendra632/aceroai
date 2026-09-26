"""Assistant tools: the functions the model may call during a chat turn, plus a
dispatcher that executes a call against the user's data via the service layer.

Design guarantees (see the assistant-tools spec):

- **User-scoped by construction.** Every tool is invoked with the authenticated `user_id`;
  the model never supplies one. An id it passes is validated by the service to belong to
  that user, or the call fails.
- **Fault-tolerant.** `execute` never raises: a bad id, invalid input, or internal error
  comes back as `{"ok": False, "error": ...}` so the model can self-correct or explain, and
  the chat turn always completes.
- **Honest.** A failure is returned as a failure. The model must never be able to narrate a
  write that did not happen — that defect is why the memory tools exist at all.

Tools are thin wrappers over `app.services.*` — no business logic lives here, so the
assistant and the REST API stay identical.

**Layout.** One module per domain, each exporting `SCHEMAS` and `HANDLERS` together. Adding
a domain is adding a file and one line below; it is never editing a shared list, and a
schema cannot be added without its handler (the assertion at the bottom of this file makes
that a startup error rather than a runtime surprise). `common.py` holds the argument
parsers the domain modules share. MCP will later expose this same registry rather than a
second copy of it.
"""

import inspect
import logging
import uuid
from collections.abc import Callable

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.tools import investments, journal, memory, research, tasks
from app.db.models import Task
from app.services.errors import Duplicate, Invalid, NotFound

log = logging.getLogger(__name__)

_MODULES = (tasks, journal, memory, investments, research)

#: The tool definitions handed to the model, in a stable order.
TOOLS: list[dict] = [schema for module in _MODULES for schema in module.SCHEMAS]

_DISPATCH: dict[str, Callable] = {
    name: fn for module in _MODULES for name, fn in module.HANDLERS.items()
}


async def execute(db: Session, user_id: uuid.UUID, name: str, arguments: dict) -> dict:
    """Run one tool call and return a structured result. Never raises: unknown tools,
    invalid input, missing records, and internal errors all become an
    `{"ok": False, "error": ...}` the model can recover from.

    Async because a handler may need the network — `remember_fact` embeds the fact before
    storing it, and a fact stored without a vector can never be recalled. Sync handlers
    (the great majority) are run in a threadpool here, so no handler blocks the event loop
    and no handler has to know which kind it is.
    """
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown tool '{name}'"}
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(db, user_id, arguments or {})
        else:
            result = await run_in_threadpool(fn, db, user_id, arguments or {})
        return {"ok": True, "result": result}
    except Duplicate as exc:
        # Hand the existing record back so the assistant can point at it ("you already
        # have that one") instead of creating a second copy.
        existing = tasks.summary(exc.existing) if isinstance(exc.existing, Task) else None
        return {"ok": False, "error": str(exc), "existing": existing}
    except (Invalid, NotFound) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:  # noqa: BLE001 - a tool must never crash the chat turn
        log.warning("tool '%s' failed", name, exc_info=True)
        return {"ok": False, "error": "the tool failed to run"}


# A schema the model can see but nothing can run is a tool that always fails; a handler no
# schema advertises is dead code. Checked at import so either mistake is a startup error
# rather than a runtime surprise — and raised, not asserted, so `python -O` cannot strip it.
_schema_names = {t["function"]["name"] for t in TOOLS}
if _schema_names != set(_DISPATCH):
    raise RuntimeError(
        f"tool schemas and handlers disagree: {sorted(_schema_names ^ set(_DISPATCH))}"
    )
