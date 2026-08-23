"""The numbers the Learn section quotes, read from the running configuration.

**Why this exists.** The Learn section teaches how the system works, and teaching involves
sentences like *"recall sends at most 16 facts"*. Written into the page as a literal, that
is correct on the day and wrong later — not as a risk, as a certainty. It has already
happened once: `memory_recall_k` moved 12 → 16 on 2026-08-23, so a page written three days
earlier would have been teaching a wrong number with the authority of a diagram.

So the content writes `{recall_k}` and this endpoint serves the live value. Change a
setting, the lesson changes. There is exactly one source of truth and it is `settings`.

**Strictly read-only and derived.** No table, no migration, no state to keep in sync. The
handler builds a dict from values already in memory since startup — there is not even a
database query.

**The allow-list is a security boundary, not a convenience.** `settings` holds the database
URL, the JWT secret, both provider keys and the Telegram bot token. Serialising it wholesale
would put every one of them in a browser. So each field is named explicitly below, the
response model is typed, and `test_api_learn.py` fails the build if anything secret-shaped
ever appears here. **Never replace this with `settings.model_dump()`.**
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.schemas import LearnConstants
from app.config import settings
from app.core import tools
from app.core.composer import HISTORY_LIMIT
from app.db.models import User
from app.services import memory as memory_svc

router = APIRouter(prefix="/api/learn", tags=["learn"])


@router.get("/constants")
def get_constants(user: User = Depends(get_current_user)) -> LearnConstants:
    """Every tuning value the Learn section is allowed to quote.

    Not all of these live in `settings`. A few are module constants — the history window,
    the graph's node ceiling — because they are engineering measurements rather than
    per-environment configuration. They are read from where they are defined, for the same
    reason: so the page cannot disagree with the code.
    """
    return LearnConstants(
        # recall — how a message finds the facts that answer it
        recall_k=settings.memory_recall_k,
        recall_pool=settings.recall_pool,
        rrf_k=settings.rrf_k,
        vector_only_max=settings.vector_only_max,
        lexical_only_max=settings.lexical_only_max,
        lexical_terms_max=settings.lexical_terms_max,
        lexical_max_df=settings.lexical_max_df,
        lexical_rare_df=settings.lexical_rare_df,
        vector_only_max_distance=settings.vector_only_max_distance,
        consensus_max_distance=settings.consensus_max_distance,
        memory_recall_timeout_s=settings.memory_recall_timeout_s,
        # memory — how a fact is judged on the way in
        memory_dedup_distance=settings.memory_dedup_distance,
        embed_dim=settings.embed_dim,
        # the prompt — what the model is shown each turn
        history_limit=HISTORY_LIMIT,
        context_tasks_limit=settings.context_tasks_limit,
        tools_max_iters=settings.tools_max_iters,
        tool_count=len(tools.TOOLS),
        max_input_chars=settings.max_input_chars,
        # the knowledge map
        graph_limit=memory_svc.GRAPH_LIMIT,
        graph_warn_at=memory_svc.graph_warn_at(),
        graph_neighbours=memory_svc.GRAPH_NEIGHBOURS,
        graph_max_distance=memory_svc.GRAPH_MAX_DISTANCE,
        # observability — how long the record is kept
        span_retention_days=settings.span_retention_days,
        turn_retention_days=settings.turn_retention_days,
    )
