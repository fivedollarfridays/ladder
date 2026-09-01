"""HTTP surface over the ladder engine, for Vercel's Python runtime.

Four operations, dispatched on `?op=`. They are deliberately the same four an
agent gets over WebMCP — the browser page in `public/` is a thin client, so
anything an agent can do here a human can do with curl, and vice versa. One
implementation, two callers.

    GET  /api?op=report
    GET  /api?op=theme&terms=dog,breed
    POST /api?op=build     {"episode","guest","themes",...}
    POST /api?op=screen    {"candidates": ["...", "..."]}
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ladder import build as build_mod  # noqa: E402
from ladder import pool as pool_mod  # noqa: E402

DECK_PATH = ROOT / "data" / "sample-deck.txt"
LEDGER_PATH = ROOT / "data" / "sample-ledger.json"


def _load() -> tuple[list[dict], dict]:
    return (
        pool_mod.parse_deck(DECK_PATH.read_text()),
        json.loads(LEDGER_PATH.read_text()),
    )


def op_report(_body: dict, _params: dict) -> dict:
    """What is left, per rung. The call that stops a set being built blind."""
    deck, ledger = _load()
    avail = pool_mod.availability(deck, ledger)
    return {
        "deck_size": len(deck),
        "spent": avail["spent"],
        "available": len(avail["available"]),
        "by_tier": {str(k): v for k, v in avail["by_tier"].items()},
        "untiered": len(avail["untiered"]),
        "exhausted_tiers": [str(t) for t in avail["exhausted_tiers"]],
    }


def op_theme(_body: dict, params: dict) -> dict:
    """Deck coverage for a theme, per rung — run BEFORE authoring anything.

    Answers "how much do I have to write myself", which is the question that
    decides whether a themed episode is even buildable.
    """
    terms = [t for t in (params.get("terms", [""])[0]).split(",") if t.strip()]
    deck, ledger = _load()
    available = pool_mod.availability(deck, ledger)["available"]
    hits = build_mod.theme_hits(available, terms)
    by_tier: dict = {}
    for q in hits:
        by_tier.setdefault(str(q["difficulty"]), []).append(
            {"id": q["id"], "category": q["category"], "text": q["text"]}
        )
    uncovered = [
        r
        for r in build_mod.ROUNDS
        if not any(str(d) in by_tier for d in build_mod.RUNG_DIFFICULTY[r])
    ]
    return {
        "terms": terms,
        "matches": len(hits),
        "by_tier": by_tier,
        "rounds_with_no_coverage": uncovered,
    }


def op_build(body: dict, _params: dict) -> dict:
    """Spec -> a full set. Deterministic: same spec + same ledger, same set."""
    deck, ledger = _load()
    try:
        episode = build_mod.build(body, deck, ledger)
    except build_mod.UnfillableRung as exc:
        return {"error": "unfillable_rung", "rounds": exc.rounds, "detail": str(exc)}
    except build_mod.CategoryLeak as exc:
        return {"error": "category_leak", "detail": str(exc)}
    except KeyError as exc:
        return {"error": "bad_spec", "detail": f"missing field {exc}"}
    drawn = sum(1 for q in episode["questions"] if q["source"] != "authored")
    episode["provenance"] = {
        "drawn_from_deck": drawn,
        "authored": len(episode["questions"]) - drawn,
    }
    return episode


def op_screen(body: dict, _params: dict) -> dict:
    """Would any of these repeat something already used? Empty is the only pass."""
    deck, ledger = _load()
    candidates = body.get("candidates") or []
    conflicts = pool_mod.screen(candidates, deck, ledger)
    return {
        "checked": len(candidates),
        "clear": not conflicts,
        "collisions": conflicts,
    }


OPS = {
    "report": op_report,
    "theme": op_theme,
    "build": op_build,
    "screen": op_screen,
}


class handler(BaseHTTPRequestHandler):
    def _respond(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        # The page and the agent may be on different origins.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def _dispatch(self, body: dict) -> None:
        params = parse_qs(urlparse(self.path).query)
        name = (params.get("op", ["report"])[0]).strip()
        fn = OPS.get(name)
        if fn is None:
            self._respond(400, {"error": "unknown_op", "known": sorted(OPS)})
            return
        try:
            self._respond(200, fn(body, params))
        except Exception as exc:  # surface the reason, never a bare 500
            self._respond(500, {"error": type(exc).__name__, "detail": str(exc)[:400]})

    def do_OPTIONS(self) -> None:
        self._respond(204, {})

    def do_GET(self) -> None:
        self._dispatch({})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._respond(400, {"error": "bad_json"})
            return
        self._dispatch(body)
