"""The framework as data: ten imperatives, thirty bottlenecks, eighteen multiples.

⚠ **This file is the SEED of the theory, not the theory.** It is loaded once into
`framework_versions.spec` and read from the database thereafter. Editing it changes nothing
that has already been scored — a change reaches the running system only by creating a new
version, which is what makes a decision made in March comparable with one made in October.

**Every crossing carries where it came from.** `CONFIRMED` is stated in Narendra's own
"Master Bottleneck Map". `PARTIAL` means the framework files the bottleneck under a parent
imperative and mentions others in passing, without ever establishing the full set.

That distinction is the point of this file. The obvious shortcut — give the eight documented
bottlenecks their real counts and give the other twenty-two a 1 — scores a **gap in the
write-up** as though it were a **fact about India**. Ammunition would look structurally
narrow because that section of his notes is short, not because replacing consumed munitions
serves one imperative. A `PARTIAL` count scores what is known, and the interface says out
loud that the figure is a floor rather than a finding.

⚠ **Source note.** Narendra's original documents (`india-AB-framework-v2-exhaustive.md`,
`buffet-reflexivity.md`, the June 8 analysis) are NOT in this repository — what is here was
extracted from them by a separate research pass, recorded in `docs/phase2-framework-inputs.md`.
So every count below is at best a faithful reading of a reading. Dropping the originals into
`docs/` would let a derivation pass run against the real text and promote many PARTIALs.
"""

from __future__ import annotations

from decimal import Decimal

#: The version this file seeds. Bumped when the data below changes materially.
INDIA_AB_VERSION = 1

# --- the ten imperatives ---------------------------------------------------------------
#
# Ranked by urgency, and the order is load-bearing: his stated principle is that
# survival-driven spending outranks aspiration-driven spending.

IMPERATIVES: list[dict] = [
    {
        "id": "A1",
        "name": "Energy Sovereignty & Grid Transformation",
        "summary": (
            "~85% of crude and ~50% of gas imported, ~9.5 days of strategic reserve, and "
            "50 GW of renewables stranded for want of grid. Everything else depends on it: "
            "fabs, data centres, defence and EV charging all need reliable power."
        ),
        "urgency": "CRITICAL",
        "crisis": "Hormuz closure, LPG rationing, 50 GW stranded renewables",
        "commitment": "₹200+ trillion by 2047",
    },
    {
        "id": "A2",
        "name": "Semiconductor & Electronics Self-Reliance",
        "summary": (
            "~100% of chips imported, so every phone, missile and car depends on foreign "
            "supply. The path is packaging → components → fabrication."
        ),
        "urgency": "CRITICAL",
        "crisis": "US–China chip war, supply-chain fragmentation, defence electronics dependency",
        "commitment": "₹76,000 Cr ISM + ₹22,919 Cr ECMS PLI",
    },
    {
        "id": "A3",
        "name": "AI & Compute Sovereignty",
        "summary": (
            "India generates ~20% of the world's data and owns under 5% of its compute. The "
            "realistic play is vertical and Global-South applications, not frontier training."
        ),
        "urgency": "HIGH",
        "crisis": "US–China concentration of AI gains",
        "commitment": None,
    },
    {
        "id": "A4",
        "name": "Defence Self-Reliance",
        "summary": (
            "The world's largest defence importer, with stocks consumed in a real conflict. "
            "The shift is from platforms to electronics, drones and munitions; 70% "
            "indigenous procurement targeted by 2027."
        ),
        "urgency": "HIGH",
        "crisis": "May 2025 India–Pakistan conflict; Iran war",
        "commitment": None,
    },
    {
        "id": "A5",
        "name": "Pharma & Biotech Sovereignty",
        "summary": (
            "The world's generics supplier, importing ~35% of its API demand mostly from "
            "China. The Biosecure Act opens a CDMO and API share-shift window."
        ),
        "urgency": "HIGH",
        "crisis": "US Biosecure Act; API diversification away from China",
        "commitment": None,
    },
    {
        "id": "A6",
        "name": "Electronics Manufacturing & China+1 Capture",
        "summary": (
            "The wider manufacturing base must capture China+1. Manufacturing is 13–14% of "
            "GDP and logistics costs 16–17% of GDP against ~8% in China."
        ),
        "urgency": "HIGH",
        "crisis": "US 50% tariffs on Indian exports",
        "commitment": None,
    },
    {
        "id": "A7",
        "name": "Space Economy",
        "summary": (
            "2–3% of the global space market today against an 8–10% target (US$44B by 2033). "
            "Space Policy 2023 opened the sector to private operators."
        ),
        "urgency": "MEDIUM-HIGH",
        "crisis": None,
        "commitment": None,
    },
    {
        "id": "A8",
        "name": "Digital Economy & Fintech Dominance",
        "summary": (
            "Already a position of strength — UPI, Aadhaar, GIFT City, 1,800+ global "
            "capability centres. The job is to export India Stack and scale it."
        ),
        "urgency": "MEDIUM-HIGH",
        "crisis": None,
        "commitment": None,
    },
    {
        "id": "A9",
        "name": "Electric Vehicles & Clean Mobility",
        "summary": "30% EV penetration targeted by 2030. ~100% of lithium-ion cells imported.",
        "urgency": "MEDIUM",
        "crisis": None,
        "commitment": None,
    },
    {
        "id": "A10",
        "name": "Food & Water Security",
        "summary": (
            "~28–30% of fertiliser imported against severe water stress. Hormuz showed "
            "fertiliser shares the oil chokepoint."
        ),
        "urgency": "MEDIUM",
        "crisis": "Hormuz threat to fertiliser imports; groundwater depletion",
        "commitment": None,
    },
]

# --- the bottlenecks -------------------------------------------------------------------
#
# `crossings_status`:
#   CONFIRMED — the set is stated in his Master Bottleneck Map.
#   PARTIAL   — his notes file it under a parent and mention others in passing. The count is
#               a FLOOR. Approving a fuller set promotes it.
#
# `crisis` is EXPLICIT only where his text ties the bottleneck to one of his three named
# shocks: the Aug 2025 tariffs, the Feb 2026 Hormuz crisis, the May 2025 conflict. A window
# that is merely open (the Biosecure Act) is not a crisis — his own principle is that
# survival-driven spending outranks aspiration-driven spending, and a regulatory opening is
# the second kind. Timing still rewards it through `inflection`.

BOTTLENECKS: list[dict] = [
    # --- A1 Energy ---
    {
        "id": "B1.1",
        "name": "Power Transmission & HVDC",
        "summary": "50 GW of renewables stranded without lines; inter-regional capacity must "
        "go 120 → 168 GW by 2032",
        "crosses": ["A1", "A2", "A3", "A5", "A6", "A9"],
        "crossings_status": "CONFIRMED",
        "crisis": "IMPLIED",
        "inflection": "NOW",
        "inflection_text": "NOW (peak FY26–30)",
        "investability": "GREEN",
        "super": True,
    },
    {
        "id": "B1.2",
        "name": "Battery Energy Storage & Cell Manufacturing",
        "summary": "236 GWh of storage needed by 2032 against under 1 GWh today; 100% of "
        "cells imported",
        "crosses": ["A1", "A3", "A9"],
        "crossings_status": "CONFIRMED",
        "crisis": "EXPLICIT",
        "inflection": "FY27",
        "inflection_text": "FY27–28 (may pull to FY26–27)",
        "investability": "AMBER",
        "super": True,
        "aliases": ["B9.1"],
    },
    {
        "id": "B1.3",
        "name": "Smart Grid & Metering",
        "summary": "25 crore meters mandated against 5.83 crore installed; AT&C losses ~15%",
        "crosses": ["A1", "A6", "A8"],
        "crossings_status": "CONFIRMED",
        "crisis": "EXPLICIT",
        "inflection": "NOW",
        "inflection_text": "NOW (FY26–29)",
        "investability": "GREEN",
    },
    {
        "id": "B1.4",
        "name": "Nuclear Energy",
        "summary": "7.5 GW today against a 100 GWe target by 2047; the SHANTI Act opens it "
        "to private operators",
        "crosses": ["A1"],
        "crossings_status": "PARTIAL",
        "crisis": "EXPLICIT",
        "inflection": "FY28",
        "inflection_text": "FY28–30 SMRs; FY32+ thorium",
        "investability": "AMBER",
    },
    {
        "id": "B1.5",
        "name": "Solar Cell & Module Manufacturing",
        "summary": "Domestic cell and module capacity against Chinese oversupply; ALMM is "
        "the policy protection and the policy risk",
        # ⚠ PROPOSED, not from his notes. His material treats solar generation only as a
        # CUSTOMER of transmission and names no bottleneck for making the cells. Added because
        # a holding (Premier Energies) otherwise has nowhere to sit — and it is the same shape
        # as B1.2: a component India imports and must learn to build.
        "crosses": ["A1", "A6"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "NOW",
        "inflection_text": "NOW (ALMM in force)",
        "investability": "AMBER",
        "proposed": True,
    },
    # --- A2 Semiconductors ---
    {
        "id": "B2.1",
        "name": "OSAT & Packaging",
        "summary": "India's semiconductor on-ramp; Kaynes is the first private OSAT",
        "crosses": ["A2", "A3", "A4", "A7"],
        "crossings_status": "CONFIRMED",
        "crisis": "EXPLICIT",
        "inflection": "FY27",
        "inflection_text": "FY27",
        "investability": "GREEN",
        "super": True,
    },
    {
        "id": "B2.2",
        "name": "Electronics Component Manufacturing",
        "summary": "60–70% of output is still assembly; PCBs, displays and passives are missing",
        # His portfolio table also maps Syrma to defence and to manufacturing, so the real
        # count is probably 3. Left at the floor until approved.
        "crosses": ["A2"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY27",
        "inflection_text": "FY27–28",
        "investability": "AMBER",
    },
    {
        "id": "B2.3",
        "name": "Fab Manufacturing",
        "summary": "Tata–PSMC 28 nm fab, Gujarat",
        "crosses": ["A2"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28–29 at earliest",
        "investability": "AMBER",
    },
    {
        "id": "B2.4",
        "name": "Ultra-Reliable Power & Water for Fabs",
        "summary": "Fabs need 100+ MW of continuous power and ultra-pure water",
        "crosses": ["A2"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "not stated",
        "investability": "GREEN",
    },
    # --- A3 AI & compute ---
    {
        "id": "B3.1",
        "name": "Data Centre & Compute Infrastructure",
        "summary": "1.4 GW today against 9 GW needed by 2030",
        "crosses": ["A1", "A3", "A8"],
        "crossings_status": "CONFIRMED",
        "crisis": "NO",
        "inflection": "FY27",
        "inflection_text": "FY27–30",
        "investability": "AMBER",
        "aliases": ["B8.2"],
    },
    {
        "id": "B3.2",
        "name": "AI Chip Access & Domestic Alternatives",
        "summary": "Nvidia holds 80–95% of the market; no Indian alternative exists",
        "crosses": ["A3"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY30",
        "inflection_text": "FY30+",
        "investability": "RED",
    },
    {
        "id": "B3.3",
        "name": "AI Talent Retention & Development",
        "summary": "Brain drain and a PhD pipeline gap",
        "crosses": ["A3"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "gradual, 3–5 years",
        "investability": "AMBER",
    },
    # --- A4 Defence ---
    {
        "id": "B4.1",
        "name": "Defence Electronics & EMS",
        "summary": "Without domestic electronics, 'indigenous' defence is assembly",
        "crosses": ["A4"],
        "crossings_status": "PARTIAL",
        "crisis": "IMPLIED",
        "inflection": "NOW",
        "inflection_text": "NOW",
        "investability": "GREEN",
    },
    {
        "id": "B4.2",
        "name": "Ammunition & Explosives",
        "summary": "Stock consumed in conflict must be replaced",
        "crosses": ["A4"],
        "crossings_status": "PARTIAL",
        "crisis": "EXPLICIT",
        "inflection": "NOW",
        "inflection_text": "NOW (FY26–28)",
        "investability": "GREEN",
    },
    {
        "id": "B4.3",
        "name": "Advanced Materials & Propulsion",
        "summary": "Superalloys, composites and propellants",
        "crosses": ["A4"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY27",
        "inflection_text": "FY27–28",
        "investability": "AMBER",
    },
    # --- A5 Pharma ---
    {
        "id": "B5.1",
        "name": "Bulk Drug & API Scale",
        "summary": "Fermentation, complex and high-potency APIs where China dominates",
        "crosses": ["A5", "A10"],
        "crossings_status": "CONFIRMED",
        "crisis": "NO",
        "inflection": "NOW",
        "inflection_text": "NOW",
        "investability": "GREEN",
    },
    {
        "id": "B5.2",
        "name": "CDMO / CRAMS",
        "summary": "India's 'IT outsourcing' for pharma",
        "crosses": ["A5", "A10"],
        "crossings_status": "CONFIRMED",
        "crisis": "NO",
        "inflection": "NOW",
        "inflection_text": "NOW",
        "investability": "GREEN",
    },
    {
        "id": "B5.3",
        "name": "Biotech & Biosimilars",
        "summary": "GMP-grade biomanufacturing at scale",
        "crosses": ["A5"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY27",
        "inflection_text": "FY27–30",
        "investability": "AMBER",
    },
    # --- A6 Manufacturing ---
    {
        "id": "B6.1",
        "name": "Logistics & Supply Chain",
        "summary": "Logistics costs 16–17% of GDP against ~8% in China",
        "crosses": ["A5", "A6"],
        "crossings_status": "CONFIRMED",
        "crisis": "IMPLIED",
        "inflection": "FY27",
        "inflection_text": "FY27–28",
        "investability": "GREEN",
    },
    {
        "id": "B6.2",
        "name": "Skilled Manufacturing Workforce",
        "summary": "CNC operators, clean-room and process engineers",
        "crosses": ["A6"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "not stated",
        "investability": "AMBER",
    },
    {
        "id": "B6.3",
        "name": "Industrial Land & Infrastructure",
        "summary": "Plug-and-play industrial parks",
        "crosses": ["A6"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28–30",
        "investability": "AMBER",
    },
    # --- A7 Space ---
    {
        "id": "B7.1",
        "name": "Private Launch Vehicles",
        "summary": "ISRO-dependent; PSLV failures",
        "crosses": ["A7"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28–30",
        "investability": "AMBER",
    },
    {
        "id": "B7.2",
        "name": "Satellite Manufacturing & Space Electronics",
        "summary": "Radiation-hardened electronics, synthetic-aperture radar",
        "crosses": ["A7"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28–30",
        "investability": "AMBER",
    },
    {
        "id": "B7.3",
        "name": "Space Applications & Data",
        "summary": "Earth observation and geospatial services",
        "crosses": ["A7"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28–30",
        "investability": "AMBER",
    },
    # --- A8 Digital ---
    {
        "id": "B8.1",
        "name": "Cybersecurity & Data Protection",
        "summary": "702 attacks a minute; DPDP Act and CERT-In audits",
        "crosses": ["A8"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "NOW",
        "inflection_text": "NOW",
        "investability": "AMBER",
    },
    {
        "id": "B8.3",
        "name": "Digital Payments & Financial Infrastructure",
        "summary": "UPI internationalisation, rupee settlement, GIFT City",
        "crosses": ["A8"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "NOW",
        "inflection_text": "NOW",
        "investability": "GREEN",
    },
    # --- A9 EV ---
    {
        "id": "B9.2",
        "name": "Charging Infrastructure",
        "summary": "22,100 fast chargers planned; ten times more needed",
        "crosses": ["A9"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "not stated",
        "investability": "AMBER",
    },
    {
        "id": "B9.3",
        "name": "EV Power Electronics & Motors",
        "summary": "SiC MOSFETs and IGBTs are imported",
        "crosses": ["A9"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "not stated",
        "investability": "AMBER",
    },
    # --- A10 Food & water ---
    {
        "id": "B10.1",
        "name": "Fertiliser Self-Sufficiency",
        "summary": "~28% of urea, ~90% of potash and ~50% of DAP imported",
        "crosses": ["A10"],
        "crossings_status": "PARTIAL",
        "crisis": "EXPLICIT",
        "inflection": "FY27",
        "inflection_text": "FY27 (post-crisis)",
        "investability": "GREEN",
    },
    {
        "id": "B10.2",
        "name": "Water Treatment & Recycling",
        "summary": "Industrial-grade water for fabs and data centres",
        "crosses": ["A10"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": "FY28",
        "inflection_text": "FY28+",
        "investability": "AMBER",
    },
    {
        "id": "B10.3",
        "name": "Agri-Tech & Supply Chain",
        "summary": "30–40% of produce lost to poor cold chain",
        "crosses": ["A10"],
        "crossings_status": "PARTIAL",
        "crisis": "NO",
        "inflection": None,
        "inflection_text": "not stated",
        "investability": "AMBER",
    },
]

# --- fair multiples --------------------------------------------------------------------
#
# What a rupee of owner earnings is worth in each sector. ⚠ Deliberately crude and stable:
# a rough number computed the same way every month can be compared across months, and a
# sophisticated one computed differently each time cannot.
#
# `source` is NOTES where Narendra's own material gives the number, and ANCHOR where it was
# set from the Nifty's long-run level (~20×) and sector character.

MULTIPLES: dict[str, dict] = {
    "DEFAULT": {
        "multiple": Decimal(20),
        "source": "ANCHOR",
        "why": "≈ Nifty's long-run level; neutral, slightly conservative",
    },
    "CAPITAL_GOODS_POWER_EQUIPMENT": {
        "multiple": Decimal(28),
        "source": "NOTES",
        "why": "his 'fair PE 25–30x for a top-quality industrial', midpoint",
    },
    "DEFENCE_MANUFACTURING": {
        "multiple": Decimal(30),
        "source": "NOTES",
        "why": "his 30–35x, held at the low end: order-book lumpy and government-paced",
    },
    "CABLES_CONDUCTORS": {
        "multiple": Decimal(26),
        "source": "NOTES",
        "why": "his implied ≥26x for Apar; commodity-linked inputs, ~9% EBITDA",
    },
    "AUTO_COMPONENTS": {
        "multiple": Decimal(20),
        "source": "NOTES",
        "why": "his '~20x not expensive'; cyclical price-taker, weak moat",
    },
    "PRIVATE_BANK": {
        "multiple": Decimal(18),
        "source": "NOTES",
        "why": "his own buy rule, 'below PE 18x'. Applied to PAT — see the bank note",
    },
    "EMS_ELECTRONICS": {
        "multiple": Decimal(25),
        "source": "ANCHOR",
        "why": "asset-light but low margin and working-capital heavy",
    },
    "PHARMA_CDMO": {
        "multiple": Decimal(30),
        "source": "ANCHOR",
        "why": "multi-year client lock-in; his '11-year tenure' argument",
    },
    "PHARMA_GENERICS_API": {
        "multiple": Decimal(22),
        "source": "ANCHOR",
        "why": "US-FDA and pricing-erosion risk; less sticky than CDMO",
    },
    "SMART_METERING": {
        "multiple": Decimal(22),
        "source": "ANCHOR",
        "why": "annuity-like AMISP revenue against DISCOM receivable risk",
    },
    "SOLAR_MANUFACTURING": {
        "multiple": Decimal(18),
        "source": "ANCHOR",
        "why": "real demand, Chinese oversupply, ALMM protection is policy-dependent",
    },
    "SPECIALTY_CHEMICALS": {
        "multiple": Decimal(24),
        "source": "ANCHOR",
        "why": "mid-cycle Indian specialty level; high variance",
    },
    "IT_SERVICES": {
        "multiple": Decimal(22),
        "source": "ANCHOR",
        "why": "mature and cash-generative, growth slowing",
    },
    "LOGISTICS_PORTS": {
        "multiple": Decimal(20),
        "source": "ANCHOR",
        "why": "infrastructure-like and capital heavy",
    },
    "EXCHANGES_MARKET_INFRA": {
        "multiple": Decimal(30),
        "source": "ANCHOR",
        "why": "high-ROE, asset-light near-monopolies",
    },
    "REGULATED_UTILITY_TRANSMISSION": {
        "multiple": Decimal(12),
        "source": "ANCHOR",
        "why": "regulated returns; bond-like, near the no-growth anchor",
    },
    "FERTILISERS": {
        "multiple": Decimal(12),
        "source": "ANCHOR",
        "why": "subsidy-regulated, low growth",
    },
    "EPC_WATER_INFRA": {
        "multiple": Decimal(15),
        "source": "ANCHOR",
        "why": "execution and working-capital heavy, lumpy order flow",
    },
    "COMMODITY_METALS": {
        "multiple": Decimal(8),
        "source": "ANCHOR",
        "why": "cyclical; the no-growth anchor",
    },
}

#: Sectors valued on profit rather than owner earnings. ⚠ For a bank, depreciation and capex
#: are immaterial, net-debt/EBITDA is meaningless, and borrowings are raw material rather than
#: leverage. Proven, not assumed: HDFC Bank's filing is `INTEGRATED_FILING_BANKING_*` and
#: carries `InterestEarned` and `InterestExpended` where an industrial carries revenue and
#: finance costs. Without this the portfolio's anchor holding scores as a value trap and the
#: gates would block it for ever.
EARNINGS_ONLY_SECTORS = frozenset({"PRIVATE_BANK"})

#: How the structural score is built. Sums to 10.
AB_WEIGHTS = {
    # ⚠ Lists, not tuples. Postgres has no tuple, so a tuple written here comes back from
    # JSONB as a list — which made an unchanged framework compare unequal to itself, and the
    # seed installed a brand-new version on every single run.
    "breadth": {"max": 4, "bands": [[6, 4], [3, 3], [2, 2], [1, 1]]},
    "crisis": {"max": 2},
    "timing": {"max": 2},
    "commitment": {"max": 1},
    "investability": {"max": 1, "GREEN": 1.0, "AMBER": 0.5, "RED": 0.0},
}


def spec() -> dict:
    """The whole theory as one JSON-serialisable object, for `framework_versions.spec`."""
    return {
        "version": INDIA_AB_VERSION,
        "imperatives": IMPERATIVES,
        "bottlenecks": BOTTLENECKS,
        "multiples": {
            key: {**row, "multiple": str(row["multiple"])} for key, row in MULTIPLES.items()
        },
        "earnings_only_sectors": sorted(EARNINGS_ONLY_SECTORS),
        "ab_weights": AB_WEIGHTS,
    }
