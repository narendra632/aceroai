"""Re-derive the recall numbers in the design docs, instead of trusting them.

    uv run python -m app.scripts.measure_recall

Prints, for a set of real queries against the real memory: how many facts the old
vector-only path returned, how many hybrid recall returns, and which ranker found each.
Every number quoted in `docs/ARCHITECTURE.md` and the OpenSpec design comes from here, so
if the behaviour drifts this is what catches it.

Costs one embedding call per query. Read-only: it writes nothing.
"""

import asyncio
import time

from sqlalchemy import select

from app.config import settings
from app.core import llm
from app.core import recall as hybrid
from app.core.memory import recall_facts
from app.db.models import User
from app.db.session import SessionLocal

QUERIES = [
    "remind me about my exam",
    "which certifications do I have",
    "where do I work",
    "when do I go to the gym",
    "what should I do today",
    "hello",
    "write a python function to reverse a list",
]

# The case that motivated lexical-only admission: several subjects at once, where the
# embedding averages them into a point that sits near nothing in particular.
LONG = (
    "Work has been heavy since the migration started and I am on call every other week, "
    "which is eating into my evenings and I want to get back to the gym properly. "
    "I still have not booked the next exam voucher and the certification I already have "
    "is the one I care about. My sister asked about Rakshabandhan plans as well."
)

SHOW_FACTS_FOR = {"where do I work", "which certifications do I have", LONG}


async def main() -> None:
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email.notlike("pytest-%"))).scalars().first()
        if user is None:
            print("no real user in this database")
            return
        header = (
            f"{'query':<44} {'before':>7} {'after':>6} {'both':>5} {'vec':>4} {'lex':>4} {'ms':>8}"
        )
        print(header)
        print("-" * len(header))
        for q in [*QUERIES, LONG]:
            vec = (await llm.embed([q]))[0]
            before = len(recall_facts(db, user, vec, settings.memory_recall_k))
            t0 = time.perf_counter()
            facts = hybrid.search(db, user, q, vec)
            ms = (time.perf_counter() - t0) * 1000
            lanes = {
                lane: sum(1 for f in facts if f.via == lane)
                for lane in (hybrid.BOTH, hybrid.VECTOR, hybrid.LEXICAL)
            }
            label = q if len(q) < 44 else q[:41] + "..."
            print(
                f"{label:<44} {before:>7} {len(facts):>6} {lanes[hybrid.BOTH]:>5} "
                f"{lanes[hybrid.VECTOR]:>4} {lanes[hybrid.LEXICAL]:>4} {ms:>6.1f}ms"
            )
            if q in SHOW_FACTS_FOR:
                words, rare = hybrid.choose_terms(db, user.id, q)
                print(f"        terms : {words}")
                print(f"        rare  : {sorted(rare)}")
                for i, f in enumerate(facts, 1):
                    print(f"        {i:>2}. [{f.via:<7}] {f.fact[:64]}")
        print(
            "\n'before' is the old vector-only path at the same k. A ceiling that never "
            "binds is the point:\nthe last row of QUERIES should read 0."
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
