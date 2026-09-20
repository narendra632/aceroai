"""Install the framework, and propose where each tracked company sits in it.

    uv run python -m app.scripts.seed_framework          # write it
    uv run python -m app.scripts.seed_framework --check  # report only, write nothing

Idempotent. Running it again when `framework_data` has not changed writes nothing; running it
after a change installs a **new version** and leaves the old one in place, because every score
already made points at the version that produced it.

⚠ **Mappings are proposed, never approved, by this script.** Seeding a company as "approved"
would defeat the one guard the structural score rests on — that a claim about national
importance is worth nothing until a person agrees with it. The rows land unapproved, they
score zero, and the Investments page lists them for you to confirm. That the first batch comes
from your own documents rather than from a model does not change the rule; a rule with an
exception for trusted sources is a rule that will acquire more exceptions.
"""

from __future__ import annotations

import argparse
import json
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import FrameworkVersion, Instrument
from app.db.session import SessionLocal
from app.services.investments import framework_data, frameworks

#: Which bottleneck each tracked company clears. From Narendra's own portfolio table.
#:
#: ⚠ `None` means off-framework and is a real answer, not a gap:
#:   SPCX       — the framework asks what INDIA must build; a US company is not answering it
#:   ROLEXRINGS — he states plainly that it is not in the framework
#: Both are still tracked, priced and reported. They are simply never scored structurally,
#: and the off-framework cap governs how much of the book they may occupy.
MAPPINGS: dict[str, str | None] = {
    "HDFCBANK": "B8.3",
    "KAYNES": "B2.1",
    "GVT&D": "B1.1",
    "SAILIFE": "B5.2",
    "SPCX": None,
    "APARINDS": "B1.1",
    "SOLARINDS": "B4.2",
    "NEULANDLAB": "B5.2",
    "GENUSPOWER": "B1.3",
    "SYRMA": "B2.2",
    "PREMIERENE": "B1.5",
    "ROLEXRINGS": None,
}

#: Why each mapping was made, in the words a person reads before agreeing with it.
WHY: dict[str, str] = {
    "HDFCBANK": (
        "Digital payments and financial infrastructure. ⚠ The June analysis labels this "
        "'B8.1 financial infrastructure', but B8.1 is Cybersecurity in the framework — B8.3 "
        "is the one that means what the sentence says."
    ),
    "KAYNES": "India's first private OSAT; the semiconductor on-ramp.",
    "GVT&D": "Transmission and HVDC equipment — the widest bottleneck in the framework.",
    "SAILIFE": "CDMO, the pharma outsourcing share-shift.",
    "SPCX": (
        "Off-framework by construction: a US company, and the framework asks what India must "
        "build. Tracked and valued; never scored structurally."
    ),
    "APARINDS": "Conductors and cables for the transmission build-out.",
    "SOLARINDS": "Explosives and ammunition — replacing stock consumed in conflict.",
    "NEULANDLAB": "CDMO, alongside Sai Life.",
    "GENUSPOWER": "Smart metering under the mandated 25-crore meter rollout.",
    "SYRMA": (
        "Electronics component manufacturing. ⚠ The portfolio table also places it under "
        "defence and under the wider manufacturing base, so its breadth is likely understated "
        "at the recorded floor."
    ),
    "PREMIERENE": (
        "Solar cell and module manufacturing. ⚠ B1.5 is PROPOSED, not from the framework — "
        "his notes treat solar only as a customer of transmission and name no bottleneck for "
        "building the cells. Approving this mapping also accepts that bottleneck."
    ),
    "ROLEXRINGS": (
        "Off-framework: he states plainly that it is not in the framework. Capped in "
        "aggregate rather than scored."
    ),
}


def _install_if_changed(db: Session, *, write: bool) -> tuple[FrameworkVersion | None, str]:
    """Install the current framework data, unless an identical version is already approved."""
    spec = framework_data.spec()
    newest = db.execute(
        sa.select(FrameworkVersion)
        .where(FrameworkVersion.family == "india_ab")
        .order_by(FrameworkVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    # ⚠ Compared through a JSON round-trip rather than directly. Postgres has no tuple, so
    # anything written as one returns as a list — and an unchanged framework then compared
    # unequal to itself, installing a fresh version on every run. Normalising both sides means
    # a future tuple cannot reintroduce it.
    if newest is not None and newest.spec == json.loads(json.dumps(spec)):
        return newest, f"framework already at v{newest.version}, unchanged"
    if not write:
        return (
            newest,
            "framework WOULD be installed" if newest is None else "framework WOULD be updated",
        )

    # ⚠ Approved on install, unlike the mappings. The theory is the user's own written
    # framework rather than a machine's reading of a company, and refusing to score against
    # anything until he clicks a button on his own document would be ceremony, not a guard.
    row = frameworks.install(
        db,
        spec,
        notes=f"seeded from framework_data v{framework_data.INDIA_AB_VERSION}",
        approved=True,
    )
    return row, f"installed framework v{row.version}"


def seed(db: Session, *, write: bool = True) -> dict:
    version, note = _install_if_changed(db, write=write)
    report: dict = {"framework": note, "proposed": [], "already": [], "missing": []}
    if version is None:
        return report

    spec = version.spec
    for symbol, b_id in MAPPINGS.items():
        inst = db.execute(
            sa.select(Instrument).where(
                Instrument.symbol == symbol, Instrument.deleted_at.is_(None)
            )
        ).scalar_one_or_none()
        if inst is None:
            report["missing"].append(symbol)
            continue

        existing = frameworks.live_mapping(db, inst.id)
        if (
            existing is not None
            and existing.b_bottleneck == b_id
            and (existing.off_framework == (b_id is None))
        ):
            report["already"].append(symbol)
            continue
        if not write:
            report["proposed"].append(f"{symbol} -> {b_id or 'off-framework'} (would propose)")
            continue

        frameworks.propose_mapping(
            db,
            inst,
            b_bottleneck=b_id,
            spec=spec,
            framework_version_id=version.id,
            proposed_by="USER",
            rationale=WHY.get(symbol),
            off_framework=b_id is None,
        )
        report["proposed"].append(f"{symbol} -> {b_id or 'off-framework'}")

    if write:
        db.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        report = seed(db, write=not args.check)
        spec = frameworks.current(db).spec if not args.check else framework_data.spec()

        print(report["framework"])
        print(
            f"  {len(spec['imperatives'])} imperatives, {len(spec['bottlenecks'])} bottlenecks, "
            f"{len(spec['multiples'])} multiples"
        )
        for line in report["proposed"]:
            print(f"  proposed  {line}")
        for symbol in report["already"]:
            print(f"  already   {symbol}")
        for symbol in report["missing"]:
            print(f"  MISSING   {symbol} - not an instrument; seed investments first")

        if not args.check:
            pending = frameworks.needs_attention(db, spec)
            print(f"\n{len(pending)} items need you:")
            for item in pending:
                print(f"  [{item.kind:13}] {item.symbol:11} {item.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
