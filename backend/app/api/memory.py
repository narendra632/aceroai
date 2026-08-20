"""The first HTTP surface for `profile_facts`.

Until this router existed, the assistant carried inferred conclusions about the user into
every conversation on every channel with no way for them to be read, corrected, or removed.
Facts were written by `core/memory.py` and read only by the recall query.

Routes are thin. Every rule — ownership, visibility, supersession — lives in
`services/memory.py`, so the API and the model's recall path cannot disagree about what is
visible. Service errors are mapped to status codes by the handlers in `main.py`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import (
    FactDetailOut,
    FactOut,
    FactPatch,
    GraphEdge,
    GraphNode,
    GraphOut,
    MemoryStatsOut,
)
from app.core import llm
from app.core.providers.base import ProviderError
from app.db.models import User
from app.db.session import get_db
from app.services import memory as svc
from app.services.errors import NotFound

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/facts")
def list_facts(
    category: str | None = None,
    status: str | None = "active",
    source: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    q: str | None = None,
    limit: int = Query(default=svc.PAGE_SIZE, ge=1, le=svc.LIST_MAX),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FactOut]:
    """The memory as it currently stands. `status=all` includes superseded facts."""
    rows = svc.list_facts(
        db,
        user.id,
        category=category,
        status=None if status == "all" else status,
        source=source,
        min_confidence=min_confidence,
        q=q,
        limit=limit,
        offset=offset,
    )
    return [FactOut.model_validate(r) for r in rows]


@router.get("/facts/{fact_id}")
def get_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactDetailOut:
    """One fact with its provenance and the version it replaced.

    Provenance is the answer to "where did you get that?" — without it a wrong belief can
    only be deleted, never argued with.
    """
    fact = svc.get_fact(db, user.id, fact_id)
    previous = svc.previous_version(db, user.id, fact)
    resembles = None
    if fact.possible_duplicate_of is not None:
        # Best-effort: the twin may since have been forgotten, and a dangling flag must not
        # turn the detail panel into a 404.
        try:
            resembles = FactOut.model_validate(
                svc.get_fact(db, user.id, fact.possible_duplicate_of)
            )
        except NotFound:
            resembles = None
    return FactDetailOut(
        **FactOut.model_validate(fact).model_dump(),
        source_session_id=svc.provenance(db, user.id, fact),
        previous=FactOut.model_validate(previous) if previous is not None else None,
        resembles=resembles,
    )


@router.get("/graph")
def get_graph(
    k: int = Query(default=svc.GRAPH_NEIGHBOURS, ge=1, le=12),
    max_distance: float = Query(default=svc.GRAPH_MAX_DISTANCE, ge=0.0, le=2.0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GraphOut:
    """Facts as nodes, semantic similarity as edges.

    `max_distance` is exposed so the UI can offer a "connection strength" control: raising
    it draws more, weaker links. Without a cutoff a kNN graph always draws `k` edges per
    node, implying relationships that aren't there.
    """
    nodes = svc.list_facts(db, user.id, limit=svc.GRAPH_LIMIT)
    # Edges are scoped to exactly the facts being drawn. Computing them across the whole
    # memory would return links to facts the client never received.
    edges = svc.neighbours(db, user.id, k=k, max_distance=max_distance, among=[n.id for n in nodes])
    total = svc.stats(db, user.id)["by_status"].get("active", 0)
    return GraphOut(
        nodes=[GraphNode.model_validate(n) for n in nodes],
        edges=[GraphEdge(source=s, target=t, distance=d) for s, t, d in edges],
        truncated=total > len(nodes),
        total=total,
        render_limit=svc.GRAPH_LIMIT,
        needs_faster_layout=total >= svc.graph_warn_at(),
    )


@router.get("/stats")
def get_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemoryStatsOut:
    return MemoryStatsOut(**svc.stats(db, user.id))


@router.patch("/facts/{fact_id}")
async def update_fact(
    fact_id: uuid.UUID,
    body: FactPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactOut:
    """Correct a fact.

    Async because changing the text requires a **fresh embedding** — a replacement stored
    without one would show in the interface while never informing a conversation again,
    which is a worse failure than refusing the edit. So if embedding fails, nothing is
    written and the caller is told.
    """
    changes = body.model_dump(exclude_unset=True)
    embedding = None
    if changes.get("fact"):
        try:
            embedding = (await llm.embed([changes["fact"]]))[0]
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Couldn't re-index that fact for search right now, so the edit wasn't "
                    "saved. Please try again shortly."
                ),
            ) from exc

    fact = await run_in_threadpool(
        svc.update_fact, db, user.id, fact_id, embedding=embedding, **changes
    )
    return FactOut.model_validate(fact)


@router.post("/facts/{fact_id}/confirm")
def confirm_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactOut:
    """Promote an assistant's inference to something the user has stated."""
    return FactOut.model_validate(svc.set_confirmed(db, user.id, fact_id, True))


@router.post("/facts/{fact_id}/unconfirm")
def unconfirm_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactOut:
    """Undo a confirmation. Confirming is one click, so un-confirming must be too —
    otherwise a misclick is permanent. The model's original confidence comes back,
    because confirming never overwrote it."""
    return FactOut.model_validate(svc.set_confirmed(db, user.id, fact_id, False))


@router.post("/facts/{fact_id}/not-duplicate")
def clear_duplicate_flag(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactOut:
    """Answer the duplicate question with "these are genuinely different".

    The flag exists because deleting a suspected duplicate was destroying real facts. But a
    warning with no way to dismiss it becomes permanent furniture, so it needs an answer
    that is not "delete one of them". Merging is the other answer, and that is just
    forgetting the one you don't want — which already exists.
    """
    return FactOut.model_validate(svc.clear_duplicate_flag(db, user.id, fact_id))


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft delete — reversible via /restore for as long as the client offers Undo. The
    fact stops reaching the model immediately."""
    svc.forget_fact(db, user.id, fact_id)


@router.post("/facts/{fact_id}/restore")
def restore_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FactOut:
    return FactOut.model_validate(svc.restore_fact(db, user.id, fact_id))
