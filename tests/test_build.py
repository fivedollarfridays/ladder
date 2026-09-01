"""Building an episode's question set from a spec — deterministically.

the owner's ask: "record this process so that it's deterministic and a part of my
tooling". Before this, a set was assembled by hand, which is how one episode ended up
authored from scratch with no record of why each question was chosen.

The properties that make it tooling rather than a script that happened to work:

* **Same spec + same ledger -> same set.** No randomness anywhere. Two people
  checking a set before a shoot must see the same five questions, and a set
  regenerated after a taping must reproduce what was actually asked.
* **It cannot pick a spent question.** The whole point.
* **It cannot silently under-fill a rung.** A missing rung is the one episode failure.
  The builder raises rather than emitting a four-question episode.
* **Provenance per question.** Every row records whether it came from the deck
  (`DQ<hash>`) or was authored for this episode.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder import build as bq_build, pool as bq_pool  # noqa: E402

DECK = "\n\n".join(
    [
        "Dogs A 1\nWhat sound does a dog make?\nA bark",
        "Cats B 2\nWhat sound does a cat make?\nA meow",
        "Dogs C 3\nWhich brown dog breed looks like a dragon?\nRhodesian Ridgeback",
        # A second difficulty-3 question, off-theme on purpose: it gives rung 3 a
        # fallback when the dog one is spent, and forces the theme test to prove
        # it PREFERS the dog question rather than merely having no alternative.
        "Trains G 3\nWhat gauge is a standard railway?\n4ft 8.5in",
        "Space D 4\nHow far is the moon?\nQuite far",
        "Dogs E 5\nWhich dog went to space?\nLaika",
        "Space F DoN\nName three planets.\nMars Venus Earth",
    ]
)


def _pool() -> list[dict]:
    return bq_pool.parse_deck(DECK)


def _ledger(*spent: str) -> dict:
    return {
        "episodes": [
            {
                "episode": "prior",
                "status": "burned",
                "questions": [{"text": t} for t in spent],
            }
        ]
    }


def _spec(**over) -> dict:
    base = {
        "episode": "bq-test",
        "guest": "Test Guest",
        "shot": "2026-09-01",
        "themes": ["dog"],
    }
    base.update(over)
    return base


# ── theme matching ──────────────────────────────────────────────────────────


def test_theme_search_finds_questions_by_keyword() -> None:
    hits = bq_build.theme_hits(_pool(), ["dog"])
    assert {h["text"] for h in hits} == {
        "What sound does a dog make?",
        "Which brown dog breed looks like a dragon?",
        "Which dog went to space?",
    }


def test_theme_search_matches_category_and_answer_too() -> None:
    """A question about the Rhodesian Ridgeback is a dog question even if the
    word 'dog' lands in the answer rather than the stem."""
    hits = bq_build.theme_hits(_pool(), ["ridgeback"])
    assert len(hits) == 1


def test_theme_search_is_case_insensitive() -> None:
    assert bq_build.theme_hits(_pool(), ["DOG"]) == bq_build.theme_hits(
        _pool(), ["dog"]
    )


def test_unmatched_theme_returns_nothing_rather_than_everything() -> None:
    """A typo'd theme must not silently degrade to 'all questions' — that would
    hand back an off-theme set that looks deliberate."""
    assert bq_build.theme_hits(_pool(), ["xyzzy"]) == []


# ── the build ───────────────────────────────────────────────────────────────


def test_builds_one_question_per_rung() -> None:
    episode = bq_build.build(_spec(), _pool(), _ledger())
    assert [q["round"] for q in episode["questions"]] == [1, 2, 3, 4, 5]


def test_each_rung_respects_the_show_bibles_difficulty_band() -> None:
    """Round 4 is a blueberry/$20 question, so it must be difficulty 4 — not a
    difficulty-1 question wearing a $20 label."""
    episode = bq_build.build(_spec(), _pool(), _ledger())
    picked = {q["round"]: q for q in episode["questions"]}
    assert picked[4]["text"] == "How far is the moon?"
    assert picked[5]["text"] in {"Which dog went to space?", "Name three planets."}


def test_theme_questions_are_preferred_where_the_rung_allows() -> None:
    """Rung 3 has both a dog question and nothing else at difficulty 3, but rung
    1 must pick the dog one over a same-difficulty alternative."""
    episode = bq_build.build(_spec(themes=["dog"]), _pool(), _ledger())
    picked = {q["round"]: q for q in episode["questions"]}
    assert picked[1]["text"] == "What sound does a dog make?"
    assert picked[3]["text"] == "Which brown dog breed looks like a dragon?"


def test_earlier_theme_terms_outrank_later_ones() -> None:
    """Theme ORDER carries intent, and ties must not fall back to a hash.

    Caught on the first real build: a themed set asked for dog questions and
    round 2 came back with a HORSE (Palomino). Both it and a Great Dane question
    matched — one on "breed", one on "dog" — and the tiebreak was the deck id.
    Listing "dog" first has to mean dog wins.
    """
    deck = "\n\n".join(
        [
            "Horses H 2\nName this golden-brown horse breed.\nPalomino",
            "Dogs I 2\nName this giant dog from Scooby Doo.\nGreat Dane",
        ]
    )
    pool = bq_pool.parse_deck(deck)
    hits = bq_build.theme_hits(pool, ["dog", "breed"])
    assert bq_build.theme_rank(hits[0], ["dog", "breed"]) is not None
    best = min(hits, key=lambda q: (bq_build.theme_rank(q, ["dog", "breed"]), q["id"]))
    assert best["answer"] == "Great Dane"


def test_theme_rank_is_none_for_an_unmatched_question() -> None:
    pool = bq_pool.parse_deck("Space Z 2\nHow far is Mars?\nFar")
    assert bq_build.theme_rank(pool[0], ["dog"]) is None


def test_a_spent_question_is_never_picked() -> None:
    episode = bq_build.build(
        _spec(), _pool(), _ledger("Which brown dog breed looks like a dragon?")
    )
    assert all(
        q["text"] != "Which brown dog breed looks like a dragon?"
        for q in episode["questions"]
    )


def test_the_build_is_deterministic() -> None:
    a = bq_build.build(_spec(), _pool(), _ledger())
    b = bq_build.build(_spec(), _pool(), _ledger())
    assert a == b


# ── provenance and the locked format ────────────────────────────────────────


def test_deck_questions_carry_their_deck_id_as_source() -> None:
    episode = bq_build.build(_spec(), _pool(), _ledger())
    assert all(q["source"].startswith("DQ") for q in episode["questions"])


def test_authored_questions_are_marked_authored_and_placed_at_their_rung() -> None:
    """Supplementing is expected — the deck cannot serve every theme at every
    rung. What matters is that the ledger can always tell which is which."""
    spec = _spec(
        authored=[
            {
                "round": 2,
                "category": "Good Boys",
                "text": "Which breed yodels instead of barking?",
                "answer": "Basenji",
            }
        ]
    )
    episode = bq_build.build(spec, _pool(), _ledger())
    row = next(q for q in episode["questions"] if q["round"] == 2)
    assert row["source"] == "authored"
    assert row["answer"] == "Basenji"


def test_authored_row_wins_over_a_deck_pick_at_the_same_rung() -> None:
    spec = _spec(
        authored=[{"round": 3, "category": "C", "text": "authored q", "answer": "a"}]
    )
    episode = bq_build.build(spec, _pool(), _ledger())
    assert (
        next(q for q in episode["questions"] if q["round"] == 3)["text"] == "authored q"
    )


def test_every_row_has_the_locked_format_fields() -> None:
    episode = bq_build.build(_spec(), _pool(), _ledger())
    required = {"round", "tier", "category", "text", "answer", "source"}
    for row in episode["questions"]:
        assert required <= set(row), f"missing {required - set(row)}"


def test_episode_carries_its_identity_and_starts_reserved() -> None:
    episode = bq_build.build(_spec(), _pool(), _ledger())
    assert episode["episode"] == "bq-test"
    assert episode["guest"] == "Test Guest"
    assert episode["status"] == "reserved"


# ── it must fail loudly rather than under-fill ──────────────────────────────


def test_an_unfillable_rung_raises_rather_than_shipping_a_short_episode() -> None:
    """THE one episode guard, at build time. A four-question episode discovered on the
    day is the failure; a build error a week out is a scheduling problem."""
    thin = bq_pool.parse_deck("Only A 1\nonly question?\na\n")
    with pytest.raises(bq_build.UnfillableRung) as exc:
        bq_build.build(_spec(), thin, _ledger())
    assert "round 2" in str(exc.value).lower() or "2" in str(exc.value)


def test_the_error_names_which_rung_so_it_can_be_authored() -> None:
    thin = bq_pool.parse_deck("Only A 1\nonly question?\na\n")
    try:
        bq_build.build(_spec(), thin, _ledger())
    except bq_build.UnfillableRung as exc:
        assert exc.rounds, "the exception must say WHICH rungs need authoring"


def test_authored_rows_can_rescue_an_otherwise_unfillable_deck() -> None:
    thin = bq_pool.parse_deck("Only A 1\nonly question?\na\n")
    spec = _spec(
        authored=[
            {"round": r, "category": "C", "text": f"q{r}", "answer": "a"}
            for r in (2, 3, 4, 5)
        ]
    )
    episode = bq_build.build(spec, thin, _ledger())
    assert len(episode["questions"]) == 5


# ── A-D options ─────────────────────────────────────────────────────────────
# Added after the first review pass: the owner noticed the slate "stopped listing
# the options as you progressed". The locked format needs to CARRY them, not
# just have them exist in a doc — one episode's row proved the cost, where the
# options lived only in kai-studio's ledger and ops held a bare stem.


def test_an_authored_question_keeps_its_options() -> None:
    spec = _spec(
        authored=[
            {
                "round": 2,
                "category": "Shots Fired",
                "text": "A puppy finishes its core vaccinations at about what age?",
                "options": {
                    "A": "6 weeks",
                    "B": "16 weeks",
                    "C": "6 months",
                    "D": "1 year",
                },
                "answer": "B. 16 weeks",
            }
        ]
    )
    row = next(
        q
        for q in bq_build.build(spec, _pool(), _ledger())["questions"]
        if q["round"] == 2
    )
    assert row["options"]["B"] == "16 weeks"


def test_a_question_without_options_does_not_gain_an_empty_one() -> None:
    """Short-answer questions are a real format in this show. An empty options
    dict on one would render four blank cards."""
    row = bq_build.build(_spec(), _pool(), _ledger())["questions"][0]
    assert "options" not in row


# ── per-rung themes ─────────────────────────────────────────────────────────
# A single global theme list cannot express "hip hop at the outer rungs,
# anti-establishment in the middle". Found on a real build: "hip hop" sat
# at index 0 and BOTH middle-rung candidates contained that phrase, so it beat
# every anti-establishment term and produced an all-hip-hop set for a guest who
# asked for a blend. Reordering the flat list could not fix it.


def test_a_rung_can_override_the_global_theme_list() -> None:
    deck = "\n\n".join(
        [
            "Rap A 3\nA question about hip hop history.\nSugarhill",
            "Gov B 3\nA question about the FBI and COINTELPRO.\nCOINTELPRO",
        ]
    )
    spec = _spec(
        themes=["hip hop"],
        themes_by_round={"3": ["cointelpro"]},
        authored=[
            {"round": r, "category": "C", "text": f"q{r}", "answer": "a"}
            for r in (1, 2, 4, 5)
        ],
    )
    row = next(
        q
        for q in bq_build.build(spec, bq_pool.parse_deck(deck), _ledger())["questions"]
        if q["round"] == 3
    )
    assert "COINTELPRO" in row["text"] or "COINTELPRO" in row["answer"]


def test_rungs_without_an_override_still_use_the_global_themes() -> None:
    spec = _spec(themes=["dog"], themes_by_round={"5": ["space"]})
    picked = {
        q["round"]: q for q in bq_build.build(spec, _pool(), _ledger())["questions"]
    }
    assert picked[1]["text"] == "What sound does a dog make?"


# ── expert calibration ──────────────────────────────────────────────────────
# The show bible's difficulty bands assume a GENERAL guest. an expert guest bartends for a
# living, so a difficulty-3 spirits question is a gimme at the $10 rung — the owner,
# reviewing the built set: "the ethan questions are too easy... bump everything
# up a tier". The money ladder and the gummies do not move; only which
# difficulty each rung draws from.


def test_a_spec_can_shift_the_difficulty_band_for_a_rung() -> None:
    deck = "\n\n".join(
        [
            "Easy A 1\nan easy one?\na",
            "Mid B 2\na mid one?\na",
            "Hard C 3\na hard one?\na",
        ]
    )
    spec = _spec(
        themes=["one"],
        difficulty_by_round={"1": [2]},  # $1 rung draws difficulty 2, not 1-2
        authored=[
            {"round": r, "category": "C", "text": f"q{r}", "answer": "a"}
            for r in (2, 3, 4, 5)
        ],
    )
    row = next(
        q
        for q in bq_build.build(spec, bq_pool.parse_deck(deck), _ledger())["questions"]
        if q["round"] == 1
    )
    assert row["text"] == "a mid one?"


def test_rungs_without_a_band_override_keep_the_bible_default() -> None:
    spec = _spec(difficulty_by_round={"1": [2]})
    picked = {
        q["round"]: q for q in bq_build.build(spec, _pool(), _ledger())["questions"]
    }
    assert picked[4]["text"] == "How far is the moon?"  # still the difficulty-4 band


def test_an_excluded_question_is_never_picked() -> None:
    """A question can be rejected FOR A GUEST without being spent. Killing the
    Negroni from an expert guest's set must not burn it — it is a fine question for
    someone who does not bartend."""
    pool = _pool()
    doomed = next(q for q in pool if q["text"] == "What sound does a dog make?")
    # Rungs 2-5 are pinned so only rung 1 draws from the deck; otherwise the
    # tiny fixture starves and we would be testing UnfillableRung, not exclusion.
    spec = _spec(
        exclude=[doomed["id"]],
        authored=[
            {"round": r, "category": "C", "text": f"q{r}", "answer": "a"}
            for r in (2, 3, 4, 5)
        ],
    )
    built = bq_build.build(spec, pool, _ledger())
    assert all(q["source"] != doomed["id"] for q in built["questions"])


def test_excluding_a_question_does_not_mark_it_spent() -> None:
    """Exclusion is per-episode preference, not a ledger burn."""
    pool = _pool()
    doomed = next(q for q in pool if q["text"] == "What sound does a dog make?")
    bq_build.build(
        _spec(
            exclude=[doomed["id"]],
            authored=[
                {"round": r, "category": "C", "text": f"q{r}", "answer": "a"}
                for r in (2, 3, 4, 5)
            ],
        ),
        pool,
        _ledger(),
    )
    still = bq_pool.availability(pool, _ledger())["available"]
    assert any(q["id"] == doomed["id"] for q in still)


# ── the category must not give away the answer ──────────────────────────────
# the owner caught this on a built card: the category read "Devil's Cut" and the
# answer was "B. The devil's cut". The header answered before the question was
# read, which makes the four options decorative.
#
# The rule has to be precise or it cries wolf. A shared word only matters if it
# DISCRIMINATES: "devil's" appeared in exactly one option (the right one), so it
# gave the game away. "Flower Power" against "orange flower water" shares
# "flower", but so do TWO of the four options — it narrows nothing and must NOT
# be flagged.


def _q(category, answer, options=None):
    return {"category": category, "answer": answer, "text": "t", "options": options}


def test_a_category_naming_the_only_matching_option_is_a_leak() -> None:
    leak = bq_build.category_leak(
        _q(
            "Devil's Cut",
            "B. The devil's cut",
            "A. The cooper's cut B. The devil's cut C. The barrel share D. The stave loss",
        )
    )
    assert leak == "devil's"


def test_a_word_shared_by_several_options_is_not_a_leak() -> None:
    """Flower Power. 'flower' appears in two options, so it discriminates
    nothing and the category is fair."""
    assert (
        bq_build.category_leak(
            _q(
                "Flower Power",
                "B. Orange flower water",
                "A. Rose water B. Orange flower water C. Elderflower cordial D. Lavender extract",
            )
        )
        is None
    )


def test_a_short_answer_question_leaks_on_any_shared_word() -> None:
    """With no options there is nothing to disambiguate against, so any overlap
    between category and answer hands it over."""
    assert bq_build.category_leak(_q("Badger Dog", "Badger dog")) == "badger"


def test_an_unrelated_category_is_clean() -> None:
    assert bq_build.category_leak(_q("Old Money", "A. The Saluki")) is None


def test_stopwords_in_common_do_not_count_as_a_leak() -> None:
    assert bq_build.category_leak(_q("The Full Monty", "The three Barrys")) is None


def test_build_refuses_a_spec_whose_authored_question_leaks() -> None:
    """Fail at build time, a week out — not on camera."""
    spec = _spec(
        authored=[
            {
                "round": 1,
                "category": "Basenji",
                "text": "which breed yodels?",
                "answer": "The Basenji",
            }
        ]
    )
    with pytest.raises(bq_build.CategoryLeak) as exc:
        bq_build.build(spec, _pool(), _ledger())
    assert "basenji" in str(exc.value).lower()


def test_a_freshly_built_set_never_leaks_a_category() -> None:
    """The live guard, against a set built from the shipped sample deck rather
    than a fixture — if any shipped question's category gave away its answer,
    build() would refuse and this would raise instead of asserting."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    deck = bq_pool.parse_deck((root / "data/sample-deck.txt").read_text())
    ledger = json.loads((root / "data/sample-ledger.json").read_text())
    episode = bq_build.build(
        {"episode": "qa", "guest": "QA", "themes": ["dog", "breed"]}, deck, ledger
    )
    for row in episode["questions"]:
        assert bq_build.category_leak(row) is None, (
            f"R{row['round']} category {row['category']!r} gives away {row['answer']!r}"
        )
