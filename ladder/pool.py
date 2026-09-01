"""What is LEFT in the deck, not just what was spent.

A ledger of what each episode USED is only half a no-repeat system. It tells you
what is spent; it cannot tell you what remains. Without the other half, building
a set means authoring from scratch and hoping, with no way to check a candidate
against history — and a tiered format makes that worse, because the deck can be
full and still be empty at the one rung tonight needs.

This module supplies the missing half: the deck lives in the repo, and
availability is `deck - reserved - burned`, computed PER DIFFICULTY RUNG.

TWO THINGS THIS GETS RIGHT ON PURPOSE
-------------------------------------
**Availability is per RUNG.** A format with one question per difficulty tier
runs dry a rung at a time, not all at once. 80 questions left is still a dead
end if tonight needs a tier 5 and all 80 are tier 2. A global count calls that
healthy.

**Matching is fuzzy, and errs toward "already used".** Ledgers are hand-typed and
paraphrase; decks carry full setups and smart quotes. Literal matching reads
spent questions as available — an error in the direction that costs a take.
Token containment over stopword-stripped text catches the drift.
"""


from __future__ import annotations

import hashlib
import re

#: Difficulty rungs the ladder actually has. Anything outside this is untiered
#: and must be triaged before a taping rather than guessed into a rung.
TIERS: tuple[int | str, ...] = (1, 2, 3, 4, 5, "DoN")

#: A ledger episode whose status starts with this is BACK in the pool. the owner
#: questions the owner has requeued are spendable
#: again and must not read as spent.
_REQUEUED = "requeued"

#: Statuses that take a question OUT of the pool. `reserved` counts: it means
#: asked on camera with the cut not yet locked, so another taping must not draw
#: it. It returns to the pool only if that episode dies.
_SPENT_STATUSES = frozenset({"reserved", "burned"})

_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_TIER_RE = re.compile(r"(?:^|\s)(?:D#)?([1-5]|DoN)\s*$", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")

#: Stripped before comparison. Without this, "what is the ... in the ..." lets
#: two unrelated questions share enough tokens to look like a match.
_STOPWORDS = frozenset(
    """a an and are as at be but by do does for from get had has have he her his
    how i if in into is it its of on or our she that the their them there these
    they this to was were what when where which who why will with you your""".split()
)

#: Token-containment score above which two questions are the same question.
#: Tuned against the real ledger-vs-deck drift; deliberately not 1.0.
_MATCH_THRESHOLD = 0.7


def normalize(text: str) -> str:
    """Case-, punctuation- and smart-quote-insensitive form used for matching."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return " ".join(_WORD_RE.findall(text.lower()))


def _tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split() if w not in _STOPWORDS}


def _similar(a: str, b: str) -> float:
    """Containment, not Jaccard.

    The ledger paraphrase is a near-subset of the deck's full setup, so its
    tokens are few and the deck's are many. Jaccard would score that pair low
    precisely when it is the same question; containment over the smaller set
    scores it high.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _parse_header(line: str) -> tuple[str, int | str | None]:
    """Split a deck header into (category, difficulty).

    Bracketed text is card/bit direction for the shoot, not part of the
    question, so it is dropped. A trailing digit is the rung; `DoN` is Double or
    Nothing. Plenty of deck rows never got a tier — those return None rather
    than a guess, because guessing a rung is how a difficulty-4 question ends up
    at $1.
    """
    line = _BRACKET_RE.sub("", line).strip()
    match = _TIER_RE.search(line)
    if not match:
        return line.strip(" :"), None
    raw = match.group(1)
    tier: int | str = "DoN" if raw.lower() == "don" else int(raw)
    return line[: match.start()].strip(" :"), tier


def parse_deck(text: str) -> list[dict]:
    """Deck text -> question records. Blocks are separated by blank lines."""
    questions: list[dict] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
        if len(lines) < 2:
            continue
        category, tier = _parse_header(lines[0])
        body = lines[1]
        rest = lines[2:]
        # An explicit `ANSWER:` line marks the correct choice and leaves the
        # options separately addressable. 67 of the 185 original deck questions
        # list A-D with NOTHING marked, which cannot be run on camera without a
        # live ruling; authored questions must not inherit that.
        options = ""
        marked = [ln for ln in rest if ln.upper().startswith("ANSWER:")]
        if marked:
            answer = marked[0].split(":", 1)[1].strip()
            options = " ".join(
                ln for ln in rest if not ln.upper().startswith("ANSWER:")
            ).strip()
        else:
            answer = " ".join(rest).strip()
        record = {
            "id": "DQ" + hashlib.sha1(normalize(body).encode()).hexdigest()[:8],
            "category": category,
            "difficulty": tier,
            "text": body,
            "answer": answer,
        }
        if options:
            record["options"] = options
        questions.append(record)
    return questions


def _spent_texts(ledger: dict) -> list[tuple[str, str]]:
    """[(question_text, status)] for every question the ledger takes out of play."""
    out: list[tuple[str, str]] = []
    for episode in ledger.get("episodes", []):
        status = (episode.get("status") or "").strip().lower()
        if status.startswith(_REQUEUED) or status not in _SPENT_STATUSES:
            continue
        for question in episode.get("questions", []):
            text = (question.get("text") or "").strip()
            if text:
                out.append((text, status))
    return out


def _haystack(question: dict) -> str:
    """The text a spent-question reference is matched against: stem PLUS answer.

    Multiple-choice stems are often generic ("Which of these came first?") with
    every distinguishing word in the options line, which parses as the answer.
    The ledger, sensibly, records such a question BY its options. Matching the
    stem alone scored those pairs near zero and reported burned questions as
    available — found in live output against the real deck, not by design.
    """
    return f"{question['text']} {question.get('answer', '')}".strip()


def match_spent(pool: list[dict], spent: list[str]) -> set[str]:
    """Ids of pool questions that one of ``spent`` refers to."""
    matched: set[str] = set()
    for used in spent:
        best_id, best = None, 0.0
        for question in pool:
            score = _similar(used, _haystack(question))
            if score > best:
                best_id, best = question["id"], score
        if best_id and best >= _MATCH_THRESHOLD:
            matched.add(best_id)
    return matched


def availability(pool: list[dict], ledger: dict) -> dict:
    """What is still spendable, per rung.

    ``by_tier`` and ``exhausted_tiers`` are keyed only by tiers the DECK
    actually contains — a rung the deck never had is not "exhausted", it was
    never stocked, and conflating the two would cry wolf on every check.
    """
    spent_ids = match_spent(pool, [t for t, _ in _spent_texts(ledger)])
    available = [q for q in pool if q["id"] not in spent_ids]

    stocked = {q["difficulty"] for q in pool if q["difficulty"] is not None}
    by_tier = {
        tier: sum(1 for q in available if q["difficulty"] == tier) for tier in stocked
    }
    order = {t: i for i, t in enumerate(TIERS)}
    return {
        "available": available,
        "by_tier": by_tier,
        "untiered": [q for q in available if q["difficulty"] is None],
        "exhausted_tiers": sorted(
            (t for t, n in by_tier.items() if n == 0), key=lambda t: order.get(t, 99)
        ),
        "spent": len(spent_ids),
    }


def screen(candidates: list[str], pool: list[dict], ledger: dict) -> list[dict]:
    """Pre-taping gate: which candidates collide with something already used.

    Run this against the night's proposed set BEFORE the shoot. An empty return
    is the only acceptable result.
    """
    conflicts: list[dict] = []
    for candidate in candidates:
        for used, status in _spent_texts(ledger):
            if _similar(candidate, used) >= _MATCH_THRESHOLD:
                conflicts.append(
                    {"candidate": candidate, "conflict": status, "clashes_with": used}
                )
                break
    return conflicts
