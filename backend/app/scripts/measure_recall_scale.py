"""What hybrid recall costs as memory grows.

    uv run python -m app.scripts.measure_recall_scale

Inserts synthetic facts for a throwaway user **inside a transaction that is rolled back**,
so the real memory is untouched and the numbers come from the actual query plans on the
real table rather than from a temp table with different statistics.

Reports the three stages separately, because "recall got slower" and "the
document-frequency probe got slower" are different problems with different fixes.

No provider calls: the query vector is synthetic, since this measures database cost and the
embedding round trip is unchanged by this feature.

An earlier version of this measurement seeded every synthetic fact with the query term and
reported 524 ms at 20k facts. That described a corpus nobody has. The vocabulary below is
deliberately varied so a search term hits a normal share of rows.
"""

import random
import time
import uuid

from sqlalchemy import text

from app.config import settings
from app.core import recall as hybrid
from app.db.models import User
from app.db.session import SessionLocal

SUBJECTS = ["Narendra", "The user"]
VERBS = [
    "completed",
    "prefers",
    "avoids",
    "scheduled",
    "reviewed",
    "cancelled",
    "started",
    "finished",
    "enjoys",
    "dislikes",
    "practises",
    "attended",
    "booked",
    "renewed",
]
SHAPES = [
    "the {} certification",
    "a trip to {}",
    "the {} meeting",
    "his {} routine",
    "the {} subscription",
    "dinner at {}",
    "the {} project",
    "a call with {}",
    "the {} appointment",
    "reading {}",
    "the {} workshop",
    "a {} class",
]
TOPICS = [
    "Azure",
    "Pune",
    "quarterly",
    "morning",
    "streaming",
    "Kyoto",
    "Helios",
    "Priya",
    "dental",
    "Berserk",
    "security",
    "pottery",
    "Mumbai",
    "annual",
    "evening",
    "Terraform",
    "Goa",
    "weekly",
    "Kafka",
    "yoga",
    "Sanjay",
    "budget",
    "Rust",
    "cycling",
    "Chennai",
    "onboarding",
    "Sunday",
    "photography",
    "Linux",
]

SHORT = "where do I work"
LONG = (
    "Work has been heavy since the Helios migration started and I am on call every other "
    "week, which is eating into my evenings, and I want to get back to cycling properly. "
    "I still have not booked the Terraform certification voucher and the dental "
    "appointment is still not sorted. Priya asked about the Goa trip in December as well, "
    "which I have not mentioned to anyone yet, and the pottery class clashes with it."
)

SIZES = (200, 1000, 5000)


def _sentence(i: int) -> str:
    return (
        f"{random.choice(SUBJECTS)} {random.choice(VERBS)} "
        f"{random.choice(SHAPES).format(random.choice(TOPICS))} (note {i})."
    )


def _unit_vec() -> list[float]:
    v = [random.gauss(0, 1) for _ in range(settings.embed_dim)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


def _timed(fn, runs: int = 10) -> float:
    fn()  # warm
    t0 = time.perf_counter()
    for _ in range(runs):
        fn()
    return (time.perf_counter() - t0) * 1000 / runs


def main() -> None:
    random.seed(11)
    db = SessionLocal()
    try:
        uid = uuid.uuid4()
        db.execute(
            text(
                "INSERT INTO users (id, email, password_hash, timezone, created_at) "
                "VALUES (:i, :e, 'x', 'Asia/Kolkata', now())"
            ),
            {"i": uid, "e": f"scale-probe-{uid}@local"},
        )
        user = db.get(User, uid)
        qvec = _unit_vec()

        header = (
            f"{'facts':>7} {'message':>8} {'DF probe':>10} {'lexical':>9} "
            f"{'vector':>8} {'total':>8} {'kept':>5} {'lex-only':>9}"
        )
        print(header)
        print("-" * len(header))
        prev = 0
        for n in SIZES:
            rows = [
                {"i": uuid.uuid4(), "u": uid, "f": _sentence(i), "v": str(_unit_vec())}
                for i in range(prev + 1, n + 1)
            ]
            db.execute(
                text(
                    "INSERT INTO profile_facts "
                    "(id, user_id, fact, category, confidence, source, status, embedding) "
                    "VALUES (:i, :u, :f, 'other', 0.8, 'inferred', 'active', cast(:v as vector))"
                ),
                rows,
            )
            prev = n
            db.execute(text("ANALYZE profile_facts"))

            for label, q in (("short", SHORT), ("long", LONG)):
                words, rare = hybrid.choose_terms(db, uid, q)
                df_ms = _timed(lambda: hybrid.choose_terms(db, uid, q))  # noqa: B023
                lex_ms = _timed(
                    lambda: hybrid.lexical_rank(db, uid, words, rare, settings.recall_pool)  # noqa: B023
                )
                vec_ms = _timed(lambda: hybrid.vector_rank(db, uid, qvec, settings.recall_pool))
                facts = hybrid.search(db, user, q, qvec)
                lex_only = sum(1 for f in facts if f.via == hybrid.LEXICAL)
                print(
                    f"{n:>7,} {label:>8} {df_ms:>8.1f}ms {lex_ms:>7.1f}ms {vec_ms:>6.1f}ms "
                    f"{df_ms + lex_ms + vec_ms:>6.1f}ms {len(facts):>5} {lex_only:>9}"
                )

        words, rare = hybrid.choose_terms(db, uid, LONG)
        print(f"\nterms chosen for the long message at {SIZES[-1]:,} facts:")
        print(f"  kept: {words}")
        print(f"  rare: {sorted(rare)}")
        print(
            "\n'vector' was already being paid before hybrid recall; the added cost is the "
            "other two.\nCompare against the ~300-500 ms embedding round trip and the "
            f"{settings.memory_recall_timeout_s:.0f} s recall budget."
        )
    finally:
        # Nothing is written. The probe user and its facts exist only inside this
        # transaction, which is why this can be run against the real table safely.
        db.rollback()
        db.close()
        print("\n(rolled back - nothing was written)")


if __name__ == "__main__":
    main()
