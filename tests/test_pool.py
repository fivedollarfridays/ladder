"""The Ladder availability check.

The failure this exists to prevent is specific and it already happened. Building
the one episode question artifact, the ledger could say what had been SPENT but there
was no pool of what was LEFT — the deck lives in Google Drive. So the set got
authored from scratch instead of drawn, with no dupe check possible. the owner's
words: a "no option scenario".

The subtraction that prevents it is per-tier, not global. The show is a ladder —
one question per rung, difficulty 1 through 5 plus Double or Nothing. A deck with
80 questions left is still a no-option scenario if all 80 are difficulty 2 and
tonight needs a 5. So `availability` reports per tier and the tests assert that.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder import pool as bq_pool  # noqa: E402

DECK = (
    Path(__file__).resolve().parents[1] / "data/sample-deck.txt"
)
LEDGER = (
    Path(__file__).resolve().parents[1] / "data/sample-ledger.json"
)


# ── parsing the deck ────────────────────────────────────────────────────────


def test_parses_category_and_difficulty_from_the_header_line() -> None:
    q = bq_pool.parse_deck(
        "Gross but True 1 [sneeze bit]\nBody fluid, two pools.\nSaliva\n"
    )
    assert len(q) == 1
    assert q[0]["category"] == "Gross but True"
    assert q[0]["difficulty"] == 1


def test_strips_stage_direction_from_the_category() -> None:
    """Bracketed text is card/bit direction, not part of the question."""
    q = bq_pool.parse_deck(
        "The GOAT 1 [Theo's head on a goat. He bahhhs]\nEGOT?\nEmmy\n"
    )
    assert "[" not in q[0]["category"] and "goat" not in q[0][
        "category"
    ].lower().replace("the goat", "")


def test_double_or_nothing_questions_carry_the_don_tier() -> None:
    q = bq_pool.parse_deck("Fool's Gold DoN\nWhat is fool's gold?\nPyrite\n")
    assert q[0]["difficulty"] == "DoN"


def test_a_header_with_no_digit_yields_no_difficulty() -> None:
    """Plenty of deck rows never got a tier. They are usable but must be
    triaged before a taping, so they are surfaced as untiered, not guessed."""
    q = bq_pool.parse_deck("Flag on the Play\nWhich flag?\nA. Spain B. Ghana\n")
    assert q[0]["difficulty"] is None


def test_every_question_gets_a_stable_id_derived_from_its_text() -> None:
    """Stable across re-parses, so the ledger can reference an id that survives
    the deck being reordered or re-transcribed."""
    text = (
        "Punfusion 2\nA burglar who steals units of energy measurement.\nJoule thief\n"
    )
    assert bq_pool.parse_deck(text)[0]["id"] == bq_pool.parse_deck(text)[0]["id"]


def test_comments_and_blank_lines_are_ignored() -> None:
    q = bq_pool.parse_deck("# SOURCE: a drive doc\n# more header\n\nOdd 1\nQ?\nA\n")
    assert len(q) == 1


# ── matching deck text to ledger text ───────────────────────────────────────


def test_normalize_ignores_case_punctuation_and_smart_quotes() -> None:
    """The ledger was hand-typed and the deck came out of a .docx, so the same
    question differs by curly apostrophes and trailing periods. If matching is
    literal, every spent question silently reads as still-available — the exact
    direction of error that causes a repeat on camera."""
    assert bq_pool.normalize("Migos aren’t:") == bq_pool.normalize("migos aren't")
    assert bq_pool.normalize("“Dark Horse” album?") == bq_pool.normalize(
        '"dark horse" album'
    )


def test_a_spent_question_is_matched_despite_wording_drift() -> None:
    """The ledger paraphrases: 'Green text bubble - what OS...' vs the deck's
    full setup. Matching must be fuzzy enough to catch that."""
    deck = (
        "Phone A Friend 1\nCongratulations! You made a friend and got their phone "
        "number. You message them and notice the text bubble is green. What "
        "operating system are they using and why are they such a peasant?\nAndroid\n"
    )
    pool = bq_pool.parse_deck(deck)
    spent = [
        "Green text bubble - what OS are they using, and why are they such a peasant?"
    ]
    assert bq_pool.match_spent(pool, spent) == {pool[0]["id"]}


def test_multiple_choice_matches_on_its_OPTIONS_not_just_its_stem() -> None:
    """Caught in live output, not by design. The deck's Double-or-Nothing stem is
    generic — "Which of these came first?" — and every distinguishing word lives
    in the options line. The ledger records that question by its options
    ("Snuggie, No Strings Attached, Razr, Phantom Menace"). Matching on the stem
    alone scored ~0, so a BURNED question read as available. That is the repeat
    -on-camera failure, reached by the safest-looking possible parse."""
    deck = (
        "Chicken or the Egg DoN\n"
        "The chicken or the egg is the eternal question. Here is a less eternal "
        "question. Which of these came first?\n"
        "A. The Snuggie (1997) B. N'Sync's \"No Strings Attached\" C. Motorola Razr "
        "D. Star Wars Episode 1: The Phantom Menace\n"
    )
    pool = bq_pool.parse_deck(deck)
    spent = ["Which came first: Snuggie, No Strings Attached, Razr, Phantom Menace?"]
    assert bq_pool.match_spent(pool, spent) == {pool[0]["id"]}


def test_an_unrelated_question_does_not_false_match() -> None:
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    assert bq_pool.match_spent(pool, ["What is the longest bone in the body?"]) == set()


# ── the subtraction ─────────────────────────────────────────────────────────


def _ledger(**episodes) -> dict:
    return {
        "rule": "test",
        "episodes": [
            {"episode": name, "status": st, "questions": [{"text": t} for t in qs]}
            for name, (st, qs) in episodes.items()
        ],
    }


def test_a_burned_question_is_not_available() -> None:
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    led = _ledger(ep1=("burned", ["Is the moon waxing to full or new?"]))
    assert bq_pool.availability(pool, led)["available"] == []


def test_a_reserved_question_is_not_available() -> None:
    """Reserved means asked on camera, cut not locked. It must not be offered to
    another taping — if the episode dies it returns to the pool, not before."""
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    led = _ledger(ep1=("reserved", ["Is the moon waxing to full or new?"]))
    assert bq_pool.availability(pool, led)["available"] == []


def test_a_requeued_question_returns_to_available() -> None:
    """the owner requeued the the prior show set on 8/18. Those must come back."""
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    led = _ledger(ep1=("requeued-2026-08-18", ["Is the moon waxing to full or new?"]))
    assert len(bq_pool.availability(pool, led)["available"]) == 1


# ── the one episode guard ─────────────────────────────────────────────────────────


def test_availability_is_reported_per_tier() -> None:
    """A rung, not the deck, is what runs dry."""
    deck = "A 1\nq one?\na\n\nB 5\nq five?\na\n\nC DoN\nq don?\na\n"
    by = bq_pool.availability(bq_pool.parse_deck(deck), _ledger())["by_tier"]
    assert by[1] == 1 and by[5] == 1 and by["DoN"] == 1


def test_a_tier_with_no_remaining_questions_is_flagged() -> None:
    """THE regression test for one episode. Tier 5 is exhausted while the deck still
    has plenty left overall — a global count would call this healthy."""
    deck = "A 1\nq one?\na\n\nB 1\nq two?\na\n\nC 5\nonly five?\na\n"
    led = _ledger(ep1=("burned", ["only five?"]))
    report = bq_pool.availability(bq_pool.parse_deck(deck), led)
    assert report["by_tier"][5] == 0
    assert 5 in report["exhausted_tiers"]
    assert len(report["available"]) == 2  # deck is NOT globally empty


def test_a_healthy_deck_flags_no_exhausted_tiers() -> None:
    deck = "A 1\nq one?\na\n\nB 5\nq five?\na\n"
    assert (
        bq_pool.availability(bq_pool.parse_deck(deck), _ledger())["exhausted_tiers"]
        == []
    )


# ── candidate screening, the pre-taping gate ────────────────────────────────


def test_a_candidate_matching_a_burned_question_is_rejected() -> None:
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    led = _ledger(ep1=("burned", ["Is the moon waxing to full or new?"]))
    bad = bq_pool.screen(["Is the moon waxing to full or new?"], pool, led)
    assert bad and bad[0]["conflict"] == "burned"


def test_a_fresh_candidate_passes_screening() -> None:
    pool = bq_pool.parse_deck(
        "Wax On 2\nIs the moon waxing to full or new?\nFull moon\n"
    )
    assert bq_pool.screen(["Something nobody has asked"], pool, _ledger()) == []


# ── the shipped artifacts must themselves hold up ───────────────────────────


@pytest.mark.skipif(not DECK.exists(), reason="deck not present")
def test_the_real_deck_parses_into_a_usable_pool() -> None:
    pool = bq_pool.parse_deck(DECK.read_text())
    assert len(pool) >= 20, f"sample deck parsed to only {len(pool)} questions"
    assert all(q["text"] for q in pool)
    # every rung the format uses must be stocked, or the sample cannot
    # demonstrate a build at all
    tiers = {q["difficulty"] for q in pool}
    for rung in (1, 2, 3, 4, 5, "DoN"):
        assert rung in tiers, f"sample deck has nothing at tier {rung}"


@pytest.mark.skipif(
    not (DECK.exists() and LEDGER.exists()), reason="deck or ledger not present"
)
def test_the_real_deck_still_has_options_at_every_tier() -> None:
    """The live guard. If this ever fails, the next taping cannot be built from
    the deck at some rung and needs new questions written BEFORE the shoot —
    which is the whole point of knowing in advance."""
    report = bq_pool.availability(
        bq_pool.parse_deck(DECK.read_text()), json.loads(LEDGER.read_text())
    )
    assert report["exhausted_tiers"] == [], (
        f"tiers with nothing left: {report['exhausted_tiers']} "
        f"(counts {report['by_tier']})"
    )


# ── explicit answers on multiple-choice ─────────────────────────────────────
# 67 of the 185 original deck questions list A-D with NO correct option marked,
# so they cannot be run on camera without someone ruling live. Newly authored
# questions must not inherit that defect: an `ANSWER:` line marks the correct
# choice and the options stay separately addressable for card rendering.


def test_an_explicit_answer_line_is_split_from_the_options() -> None:
    q = bq_pool.parse_deck(
        "Shots Fired 1\nFinishes core vaccinations at what age?\n"
        "A. 6 weeks B. 16 weeks C. 6 months D. 1 year\nANSWER: B. 16 weeks\n"
    )[0]
    assert q["answer"] == "B. 16 weeks"
    assert q["options"] == "A. 6 weeks B. 16 weeks C. 6 months D. 1 year"


def test_a_question_with_no_answer_line_keeps_todays_behaviour() -> None:
    """The 118 deck questions that DO carry a plain answer must not regress."""
    q = bq_pool.parse_deck("Hot Dog 2\nWhat does Dachshund mean?\nBadger dog\n")[0]
    assert q["answer"] == "Badger dog"
    assert not q.get("options")


def test_unmarked_multiple_choice_still_parses_as_before() -> None:
    """The 67 unmarked ones stay readable — they are a data debt to pay down,
    not a parse error."""
    q = bq_pool.parse_deck(
        "You're Wrong 3\nThis is a shade of blue:\nA. periwinkle B. cobalt\n"
    )[0]
    assert "periwinkle" in q["answer"]
