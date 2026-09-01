"""Build an episode's question set from a spec — deterministically.

Assembled by hand, a set has no record of why each question was chosen. This
makes it tooling:

**No randomness.** Same spec + same ledger -> byte-identical set.
**It cannot under-fill.** An empty rung raises `UnfillableRung` naming the rung.
**It cannot leak its own answer.** A category sharing a discriminating word with
the correct option raises `CategoryLeak`.
**Provenance per row.** Every question records its deck id, or `authored`.
"""


from __future__ import annotations

import re

from ladder import pool as bq_pool

#: Rung -> the difficulties the show bible permits there. Round 5 accepts a
#: difficulty-5 OR a Double-or-Nothing question.
RUNG_DIFFICULTY: dict[int, tuple] = {
    1: (1, 2),
    2: (1, 2),
    3: (3,),
    4: (4,),
    5: (5, "DoN"),
}

#: Rung -> the gummy/stake label written into the artifact. The gummy is eaten
#: BEFORE the question at every rung.
RUNG_TIER: dict[int, str] = {
    1: "grape / $1",
    2: "lime / $5",
    3: "carrot orange cream / $10",
    4: "blueberry / $20",
    5: "cherry-pom / Double or Nothing",
}

ROUNDS = (1, 2, 3, 4, 5)


class UnfillableRung(ValueError):
    """A rung has no available question and no authored fallback.

    Carries ``rounds`` so a caller can say exactly what needs writing, which is
    the difference between a useful failure and a wall.
    """

    def __init__(self, rounds: list[int], detail: str = "") -> None:
        self.rounds = rounds
        listed = ", ".join(f"round {r}" for r in rounds)
        super().__init__(
            f"cannot fill {listed} from the available deck. "
            f"Author question(s) for {'it' if len(rounds) == 1 else 'them'} in the "
            f"spec's `authored` list before the shoot. {detail}".strip()
        )


def _haystack(question: dict) -> str:
    return " ".join(
        [
            question.get("text", ""),
            question.get("answer", ""),
            question.get("category", ""),
        ]
    ).lower()


def theme_hits(pool: list[dict], terms: list[str]) -> list[dict]:
    """Questions matching any theme term, searched across stem, answer AND
    category.

    A Rhodesian Ridgeback question is a dog question even when the word "dog"
    lands in the answer rather than the stem, and the deck's categories carry
    real signal ("Beer Necessities", "Hip Hop Royalty").

    An unmatched term returns nothing rather than everything: a typo'd theme
    must not silently degrade into "all questions", which would hand back an
    off-theme set that looks deliberate.
    """
    lowered = [t.lower() for t in terms if t.strip()]
    if not lowered:
        return []
    return [q for q in pool if any(t in _haystack(q) for t in lowered)]


def theme_rank(question: dict, terms: list[str]) -> int | None:
    """Index of the EARLIEST theme term this question matches, or None.

    Theme order carries intent. Caught on the first real build: a set asking for
    dog questions returned a HORSE at round 2, because "Palomino" matched
    "breed" and a Great Dane question matched "dog", and the tiebreak fell
    through to the deck id. Listing "dog" first has to mean dog wins.
    """
    hay = _haystack(question)
    for i, term in enumerate(t.lower() for t in terms):
        if term and term in hay:
            return i
    return None


class CategoryLeak(ValueError):
    """The category gives away its own answer."""


#: Too common to carry signal. Sharing "the" between a category and an answer
#: means nothing; sharing "basenji" means everything.
_LEAK_STOPWORDS = frozenset(
    """a all an and are as at be but by do for from in is it its of on or that the
    this to with you your three four five six""".split()
)

_WORD = re.compile(r"[a-z']+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _LEAK_STOPWORDS}


def category_leak(question: dict) -> str | None:
    """The category word that gives away the answer, or None.

    the owner caught this on a built card: the category read "Devil's Cut" against
    the answer "B. The devil's cut", so the header answered before the question
    was read and the four options became decorative.

    The rule is deliberately narrow, because a loose one cries wolf and gets
    switched off. A shared word only counts if it DISCRIMINATES — that is, it
    appears in exactly ONE option, and that option is the answer. "Flower Power"
    against "orange flower water" shares "flower", but two of the four options
    contain it, so it narrows nothing and is fair.

    With no options there is nothing to disambiguate against, so any meaningful
    overlap hands the answer over.
    """
    shared = _words(question.get("category", "")) & _words(question.get("answer", ""))
    if not shared:
        return None
    options = question.get("options")
    if not options:
        return sorted(shared)[0]
    # Split "A. x B. y C. z" into the individual choices.
    choices = re.split(r"\s(?=[A-D][).]\s)", str(options).strip())
    for word in sorted(shared):
        if sum(1 for c in choices if word in c.lower()) == 1:
            return word
    return None


def _candidates(
    available: list[dict],
    round_no: int,
    used: set[str],
    band: tuple | list | None = None,
) -> list[dict]:
    band = band if band is not None else RUNG_DIFFICULTY[round_no]
    return [q for q in available if q["difficulty"] in band and q["id"] not in used]


def _pick(candidates: list[dict], terms: list[str]) -> dict | None:
    """Deterministic choice: best theme rank, then deck id.

    Unmatched questions sort last via a sentinel rather than being dropped, so a
    rung still fills off-theme rather than raising — an off-theme question is a
    worse episode, an empty rung is a broken one.

    The final tiebreak is the id (a content hash) rather than deck position, so
    the choice survives the deck being reordered or re-transcribed.
    """
    if not candidates:
        return None

    def key(q: dict) -> tuple:
        rank = theme_rank(q, terms)
        return (len(terms) if rank is None else rank, q["id"])

    return sorted(candidates, key=key)[0]


def _row(round_no: int, question: dict, source: str) -> dict:
    """One artifact row in the locked format.

    ``options`` is carried when present and OMITTED when not — short-answer is a
    real format in this show, and an empty dict would render four blank cards.
    one episode's row is why this field exists at all: the A-D texts lived only
    in kai-studio's ledger while ops held a bare stem, so neither file alone
    could produce a card.
    """
    row = {
        "round": round_no,
        "tier": RUNG_TIER[round_no],
        "category": question.get("category", ""),
        "text": question.get("text", ""),
        "answer": question.get("answer", ""),
        "source": source,
    }
    if question.get("options"):
        row["options"] = question["options"]
    return row


def build(spec: dict, pool: list[dict], ledger: dict) -> dict:
    """Spec + deck + ledger -> an episode in the locked artifact format."""
    available = bq_pool.availability(pool, ledger)["available"]
    terms = spec.get("themes", [])
    # Per-rung overrides. A flat list cannot express "hip hop at the outer
    # rungs, anti-establishment in the middle" — found on a real build,
    # where "hip hop" sat at index 0 and BOTH middle-rung candidates contained
    # that phrase, so it beat every anti-establishment term and produced an
    # all-hip-hop set for a guest who asked for a blend. Reordering the flat
    # list could not fix it, because rank is global while the need is per rung.
    by_round = {int(k): v for k, v in spec.get("themes_by_round", {}).items()}
    # Per-rung difficulty override. The bible's bands assume a GENERAL guest; a
    # subject-matter expert makes them wrong. an expert guest is a subject-matter expert, so a
    # difficulty-3 spirits question is a gimme at the $10 rung. Shifting the
    # bands up moves WHICH difficulty each rung draws — the money ladder and the
    # gummies do not move, because those are the show, not the calibration.
    bands = {int(k): tuple(v) for k, v in spec.get("difficulty_by_round", {}).items()}
    # Rejected FOR THIS GUEST, without being spent. A question that is wrong for
    # one contestant is usually fine for another, so exclusion must not burn it.
    excluded = set(spec.get("exclude", []))
    authored = {a["round"]: a for a in spec.get("authored", [])}

    rows: list[dict] = []
    used: set[str] = set()
    unfillable: list[int] = []

    for round_no in ROUNDS:
        if round_no in authored:
            rows.append(_row(round_no, authored[round_no], "authored"))
            continue
        pool_for_rung = [q for q in available if q["id"] not in excluded]
        choice = _pick(
            _candidates(pool_for_rung, round_no, used, bands.get(round_no)),
            by_round.get(round_no, terms),
        )
        if choice is None:
            unfillable.append(round_no)
            continue
        used.add(choice["id"])
        rows.append(_row(round_no, choice, choice["id"]))

    if unfillable:
        raise UnfillableRung(unfillable)

    for row in rows:
        leak = category_leak(row)
        if leak:
            raise CategoryLeak(
                f"round {row['round']} category {row['category']!r} gives away its own "
                f"answer {row['answer']!r} (shared discriminating word: {leak!r}). "
                f"Rename the category — the options are there to make the guest choose."
            )

    return {
        "episode": spec["episode"],
        "guest": spec["guest"],
        "shot": spec.get("shot", ""),
        "status": spec.get("status", "reserved"),
        "themes": spec.get("themes", []),
        "note": spec.get("note", ""),
        "questions": rows,
    }
