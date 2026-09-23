"""The six flags a model may answer, and the four gates it has to get past.

Almost every test here is an attempt to sneak an unsupported verdict into the record, because
that is the failure this module exists to prevent. A checklist answer that looks identical
whether it rests on a filing or on nothing is a checklist that makes a portfolio feel
examined without examining it.

⚠ Every flag is a RED flag. YES is bad.
"""

import uuid

import pytest

from app.db.models import Mention, SourceItem
from app.services.investments import judgement
from app.services.investments.scoring import Flag
from tests.conftest import make_instrument

FILING = (
    "The Company continues to invest in capacity expansion, with capital expenditure "
    "substantially exceeding depreciation in each of the last three financial years."
)
COMMENTARY = (
    "Everyone on social media is talking about this one and nobody is asking about execution "
    "risk or the order book conversion."
)


@pytest.fixture
def company(db):
    inst = make_instrument(
        db,
        symbol="JUDGECO",
        exchange="NSE",
        name="Judgeco Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(inst)
    db.flush()
    db.commit()
    return inst


@pytest.fixture
def with_evidence(db, company):
    """One filing excerpt and one piece of commentary to cite from."""
    import datetime as dt

    item = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=company.id,
        source="pytest",
        external_id=f"e{uuid.uuid4().hex[:8]}",
        fetched_at=dt.datetime.now(dt.UTC),
        content_hash=uuid.uuid4().hex,
        excerpt=FILING,
    )
    db.add(item)
    db.flush()
    db.add(
        Mention(
            id=uuid.uuid4(),
            source_item_id=item.id,
            instrument_id=company.id,
            stance="BULL",
            claim_excerpt=COMMENTARY,
        )
    )
    db.commit()
    return company


def _answers(**by_number):
    """Build a model reply for the six judged flags."""
    return {"flags": [{"number": n, **row} for n, row in by_number.items()]}


def _patch(monkeypatch, answer, *, supports=True):
    async def _ask(questions, evidence):
        return answer

    async def _verify(question, verdict, quote):
        return supports

    monkeypatch.setattr(judgement, "_ask", _ask)
    monkeypatch.setattr(judgement, "_verify", _verify)


# --- which flags a model may touch at all --------------------------------------------------


def test_only_the_six_qualitative_flags_are_asked(db, with_evidence, monkeypatch):
    """⚠ The other four are measured. A measurable thing must never be a matter of opinion,
    and those four are the ones a persuasive narrative would most easily argue away."""
    _patch(monkeypatch, _answers())

    numbers = [row.number for row in judgement.judged_flags(db, with_evidence)]

    assert numbers == [1, 3, 4, 5, 7, 9]
    assert not set(numbers) & set(judgement.COMPUTED)


def test_a_verdict_on_a_computed_flag_is_discarded(db, with_evidence, monkeypatch):
    """⚠ Dropped on the floor before it reaches anything, rather than merged and overwritten
    later — a value that exists briefly is a value something can read."""
    _patch(
        monkeypatch,
        {
            "flags": [
                {"number": 6, "verdict": "YES", "quote": FILING, "why": "multiple expanded"},
                {"number": 1, "verdict": "NO", "quote": FILING, "why": "ordinary business"},
            ]
        },
    )

    rows = judgement.judged_flags(db, with_evidence)

    assert 6 not in [r.number for r in rows]


def test_the_questions_are_verbatim(db):
    """⚠ A reworded question produces an answer to a different question, and nothing
    downstream would notice."""
    assert "circle of competence" in judgement.JUDGED[1]
    assert "just to maintain" in judgement.JUDGED[3]
    assert "lack of candor" in judgement.JUDGED[5]
    assert "hype-driven narrative" in judgement.JUDGED[9]


# --- gate one: it has to cite something ----------------------------------------------------


def test_a_verdict_with_no_quote_becomes_unknown(db, with_evidence, monkeypatch):
    """⚠ Not "probably yes". A verdict without a citation is an opinion, and an opinion in
    this record is indistinguishable from a finding."""
    _patch(
        monkeypatch,
        _answers(**{"1": {"verdict": "YES", "quote": "", "why": "it feels complex"}}),
    )

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 1)

    assert row.verdict == "UNKNOWN"
    assert "citation" in row.withheld_because


def test_nothing_is_asked_when_nothing_has_been_read(db, company, monkeypatch):
    """⚠ A model given no excerpts will still answer, and its answers would be exactly the
    unsourced opinion this design exists to keep out."""
    called = []

    async def _ask(questions, evidence):
        called.append(1)
        return _answers()

    monkeypatch.setattr(judgement, "_ask", _ask)

    rows = judgement.judged_flags(db, company)

    assert called == []
    assert all(r.verdict == "UNKNOWN" for r in rows)
    assert all("nothing has been read" in r.withheld_because for r in rows)


# --- gate two: the words have to really be there -------------------------------------------


def test_a_quote_that_is_not_in_the_evidence_is_refused(db, with_evidence, monkeypatch):
    """⚠ The most important refusal here. A model that could invent its own evidence would
    make every other guard decorative."""
    _patch(
        monkeypatch,
        _answers(
            **{
                "5": {
                    "verdict": "YES",
                    "quote": "Management admitted to restating prior period results deliberately.",
                    "why": "they restated",
                }
            }
        ),
    )

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 5)

    assert row.verdict == "UNKNOWN"
    assert "not in the evidence" in row.withheld_because


def test_a_quote_that_is_really_there_survives(db, with_evidence, monkeypatch):
    _patch(
        monkeypatch,
        _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital expenditure substantially exceeding depreciation",
                    "why": "capex runs above depreciation",
                }
            }
        ),
    )

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 3)

    assert row.verdict == "YES"
    assert row.verifier_agreed is True


def test_reflowed_whitespace_still_counts_as_the_same_quote(db, with_evidence, monkeypatch):
    """A model reflowing a line is not the same as inventing one — but nothing beyond
    whitespace is forgiven, because every further liberty is a liberty with what counts as
    evidence."""
    _patch(
        monkeypatch,
        _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital   expenditure\n substantially exceeding   depreciation",
                    "why": "capex above depreciation",
                }
            }
        ),
    )

    assert (
        next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 3).verdict == "YES"
    )


def test_a_quote_too_short_to_mean_anything_is_refused(db, with_evidence, monkeypatch):
    """⚠ "growth" appears in every filing ever written and would pass an echo check against
    any of them."""
    _patch(
        monkeypatch,
        _answers(**{"1": {"verdict": "YES", "quote": "Company", "why": "short"}}),
    )

    assert (
        next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 1).verdict
        == "UNKNOWN"
    )


# --- gate three: a second reader has to agree ----------------------------------------------


def test_a_verifier_disagreement_withholds_the_flag(db, with_evidence, monkeypatch):
    """⚠ The second reader sees only the question, the verdict and the quote — never the
    company, never the other answers — so it cannot be carried along by the story."""
    _patch(
        monkeypatch,
        _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital expenditure substantially exceeding depreciation",
                    "why": "capex",
                }
            }
        ),
        supports=False,
    )

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 3)

    assert row.verdict == "UNKNOWN"
    assert row.verifier_agreed is False
    assert "second reader" in row.withheld_because


def test_the_verifier_is_shown_no_identifying_context(db, with_evidence, monkeypatch):
    seen = {}

    async def _ask(questions, evidence):
        return _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital expenditure substantially exceeding depreciation",
                    "why": "capex",
                }
            }
        )

    async def _verify(question, verdict, quote):
        seen["args"] = (question, verdict, quote)
        return True

    monkeypatch.setattr(judgement, "_ask", _ask)
    monkeypatch.setattr(judgement, "_verify", _verify)

    judgement.judged_flags(db, with_evidence)

    assert "JUDGECO" not in " ".join(seen["args"])
    assert "Judgeco" not in " ".join(seen["args"])


def test_an_unreachable_verifier_withholds_rather_than_passes(db, with_evidence, monkeypatch):
    """⚠ A verifier that cannot be reached must not become a verifier that agreed."""

    async def _ask(questions, evidence):
        return _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital expenditure substantially exceeding depreciation",
                    "why": "capex",
                }
            }
        )

    async def _verify(question, verdict, quote):
        raise RuntimeError("provider down")

    monkeypatch.setattr(judgement, "_ask", _ask)
    monkeypatch.setattr(judgement, "_verify", _verify)

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 3)

    assert row.verdict == "UNKNOWN"


# --- gate four: no arithmetic --------------------------------------------------------------


@pytest.mark.parametrize(
    "why",
    [
        "capex is 140% of depreciation",
        "ROE of 9 is weak",
        "margins fell 200 bps",
        "revenue CAGR has stalled",
    ],
)
def test_a_verdict_that_calculates_is_refused(db, with_evidence, monkeypatch, why):
    """⚠ Every number in this module comes from a filing and none comes from a model. Quoting
    a filed figure is fine; working one out is arithmetic the model is not allowed to do."""
    _patch(
        monkeypatch,
        _answers(
            **{
                "3": {
                    "verdict": "YES",
                    "quote": "capital expenditure substantially exceeding depreciation",
                    "why": why,
                }
            }
        ),
    )

    row = next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 3)

    assert row.verdict == "UNKNOWN"
    assert "comes from a filing" in row.withheld_because


# --- when everything falls over ------------------------------------------------------------


def test_an_unreachable_model_withholds_all_six(db, with_evidence, monkeypatch):
    async def _ask(questions, evidence):
        raise RuntimeError("provider down")

    monkeypatch.setattr(judgement, "_ask", _ask)

    rows = judgement.judged_flags(db, with_evidence)

    assert len(rows) == 6
    assert all(r.verdict == "UNKNOWN" for r in rows)


def test_an_answer_outside_the_vocabulary_is_refused(db, with_evidence, monkeypatch):
    _patch(
        monkeypatch,
        _answers(**{"1": {"verdict": "PROBABLY", "quote": FILING, "why": "hedging"}}),
    )

    assert (
        next(r for r in judgement.judged_flags(db, with_evidence) if r.number == 1).verdict
        == "UNKNOWN"
    )


def test_a_flag_the_model_simply_skipped_is_unknown(db, with_evidence, monkeypatch):
    _patch(monkeypatch, _answers(**{"1": {"verdict": "NO", "quote": FILING, "why": "ordinary"}}))

    rows = {r.number: r for r in judgement.judged_flags(db, with_evidence)}

    assert len(rows) == 6
    assert rows[9].verdict == "UNKNOWN"


# --- the whole checklist -------------------------------------------------------------------


def test_the_measured_flags_overwrite_the_judged_ones():
    """⚠ Where a flag can be measured, the measurement wins. Nothing about a persuasive
    argument should be able to move a number."""
    computed = [Flag(6, "computed question", "YES", "MER above 2", computed=True)]
    judged = [judgement.Judged(6, "judged question", "NO", "a quote", "reasoning")]

    result = judgement.checklist(computed, judged)

    assert len(result.flags) == 1
    assert result.flags[0].verdict == "YES"
    assert result.flags[0].computed is True


def test_partial_is_kept_but_not_counted_as_red():
    """⚠ Against the spec's three-value vocabulary and in favour of how the framework is
    actually used: the notes mark flags PARTIAL throughout and say partial flags are excluded
    from the count."""
    judged = [
        judgement.Judged(1, "q", "PARTIAL", "a quote", "r"),
        judgement.Judged(3, "q", "YES", "a quote", "r"),
    ]

    result = judgement.checklist([], judged)

    assert result.red == 1
    assert {f.verdict for f in result.flags} == {"PARTIAL", "YES"}


@pytest.mark.parametrize(
    ("reds", "band"),
    [
        (0, "Low risk"),
        (3, "Low risk"),
        (4, "Moderate risk"),
        (6, "Moderate risk"),
        (7, "High speculative risk"),
    ],
)
def test_the_bands_are_the_frameworks_own(reds, band):
    judged = [
        judgement.Judged(n, "q", "YES" if n <= reds else "NO", "a quote", "r") for n in range(1, 11)
    ]
    assert judgement.checklist([], judged).band == band


def test_a_mostly_unanswered_checklist_refuses_to_be_read(db):
    """⚠ Four YES out of four answered is not the same as four out of ten, and a band computed
    over two known flags would read exactly like one computed over all of them."""
    judged = [
        judgement.Judged(n, "q", "UNKNOWN" if n > 3 else "NO", None, "r") for n in range(1, 11)
    ]

    result = judgement.checklist([], judged)

    assert result.unknown == 7
    assert not result.is_readable


# --- the sign that is not obvious ----------------------------------------------------------


def test_an_inverted_loop_scores_negatively_while_remaining_a_buy():
    """⚠ The whole point of the sign, and it is not obvious. A negative narrative over an
    intact business — HDFC Bank's exact situation — scores NEGATIVELY on reflexivity while
    remaining a perfectly good buy. A design taking the magnitude alone would have made the
    most interesting case in the portfolio unreadable."""
    flags = [Flag(n, "q", "YES", "e") for n in (6, 9, 10)]

    assert judgement.soros_score(flags, "UP") == 3
    assert judgement.soros_score(flags, "INVERTED") == -3
    assert judgement.soros_score(flags, "DOWN") == -3


def test_only_the_soros_half_drives_reflexivity():
    """Flags 1–5 are quality overrides recorded on the score; they do not move this."""
    flags = [Flag(n, "q", "YES", "e") for n in (1, 2, 3, 4, 5)]

    assert judgement.soros_score(flags, "UP") == 0


def test_no_loop_direction_means_no_score(db):
    """⚠ Not zero. Zero is a reading; absent is the absence of one."""
    assert judgement.soros_score([Flag(6, "q", "YES", "e")], None) is None
