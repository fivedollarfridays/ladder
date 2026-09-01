"""Build an episode's question set from a spec — deterministically.

Assembled by hand, a set has no record of why each question was chosen, and
answers go unrecorded. This makes it tooling.

WHAT MAKES IT TOOLING RATHER THAN A SCRIPT
------------------------------------------
**No randomness.** Candidates are ordered by (theme match, deck id) and the
first is taken. Same spec + same ledger -> byte-identical set. Two people
checking before a shoot see the same questions, and regenerating after the fact
reproduces what was actually asked.

**It cannot under-fill.** A rung with no candidate raises `UnfillableRung`
naming the rungs, rather than emitting a short episode. A build error a week out
is a scheduling problem; a missing question discovered on the day is not.

**Provenance per row.** Every question records the deck id it came from, or
`authored`. Supplementing is expected — no deck serves every theme at every
rung — but the ledger must always be able to say which is which.
"""


from __future__ import annotations

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


def _candidates(available: list[dict], round_no: int, used: set[str]) -> list[dict]:
    band = RUNG_DIFFICULTY[round_no]
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
    One episode is why this field exists at all: the A-D texts lived only
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
    authored = {a["round"]: a for a in spec.get("authored", [])}

    rows: list[dict] = []
    used: set[str] = set()
    unfillable: list[int] = []

    for round_no in ROUNDS:
        if round_no in authored:
            rows.append(_row(round_no, authored[round_no], "authored"))
            continue
        choice = _pick(
            _candidates(available, round_no, used), by_round.get(round_no, terms)
        )
        if choice is None:
            unfillable.append(round_no)
            continue
        used.add(choice["id"])
        rows.append(_row(round_no, choice, choice["id"]))

    if unfillable:
        raise UnfillableRung(unfillable)

    return {
        "episode": spec["episode"],
        "guest": spec["guest"],
        "shot": spec.get("shot", ""),
        "status": spec.get("status", "reserved"),
        "themes": spec.get("themes", []),
        "note": spec.get("note", ""),
        "questions": rows,
    }
