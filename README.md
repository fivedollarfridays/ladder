# Ladder

A tiered question deck that an agent can read, search, and build from — but
**cannot bluff past**.

Ask a language model for five quiz questions and it will cheerfully hand you
five it has already produced. Ladder makes that impossible: the deck is finite,
it remembers what has been used, and it tells an agent **no**.

## The idea

Every question is `available`, `reserved` (asked on camera, recording not yet
locked), or `burned` (locked, spent forever). A set is one question per
difficulty rung. Everything else follows from those two rules:

- **Availability is per rung.** A deck can be 90% full and still be empty at the
  one tier tonight needs. A global count calls that healthy; this doesn't.
- **Builds are deterministic.** Same spec, same ledger, same set — byte for
  byte. Two people checking before a shoot see the same five questions, and
  regenerating afterwards reproduces what was actually asked.
- **It fails loudly rather than short.** No candidate for a rung raises
  `UnfillableRung` naming the rung, instead of quietly returning four questions.
- **Provenance per row.** Each question records the deck id it came from, or
  `authored`. Supplementing is expected; losing track of which is which is not.
- **The category can't give away the answer.** A build fails if a category shares
  a *discriminating* word with its own answer — one that appears in exactly one
  option, and that option is the right one. Caught on a real card whose category
  read "Devil's Cut" above the answer "the devil's cut".

## WebMCP

`public/index.html` registers four tools via `document.modelContext.registerTool()`:

| tool | does |
|---|---|
| `deck_report` | what remains, per rung, and which rungs are exhausted |
| `theme_search` | coverage for a theme, and which rungs it cannot cover |
| `build_set` | a full set from a spec — deterministic, refuses to under-fill |
| `screen_candidates` | would any of these repeat something already used |

They are the same four operations the HTTP API exposes, deliberately: an agent
gets no capability a person with `curl` doesn't have. One implementation, two
callers, nothing to drift.

The page works with no agent present and no JavaScript framework — the tools
simply don't register if `document.modelContext` is absent.

## Run it

```bash
python3 -m pytest tests/ -q     # 57 tests, no runtime dependencies
vercel dev                      # api/ + public/
```

The engine is pure standard library. `pytest` is the only dependency, and only
for the tests.

```
GET  /api?op=report
GET  /api?op=theme&terms=dog,breed
POST /api?op=build     {"episode":"demo","guest":"...","themes":["dog"]}
POST /api?op=screen    {"candidates":["..."]}
```

## The deck here is synthetic

21 sample questions, written for this repo. The deck it was extracted from stays
private — publishing unaired questions would spoil the show they belong to,
which is itself the argument for why a no-repeat ledger needs somewhere to live
that isn't a public repo.

## Licence

MIT.
