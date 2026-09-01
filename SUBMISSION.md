# Devpost submission — The WebMCP Challenge

Copy-paste into the Devpost form. Deadline **Sept 3, 1:00pm PDT**.

---

## Tagline

**A deck that tells the agent no.**

---

## Inspiration

Every agent-and-website demo is the agent doing things *to* a site — filling the
form, clicking the button, driving the UI faster than a person could. The site is
scenery.

I wanted the opposite: a site that **constrains** the agent. Something where the
page holds rules the agent cannot argue with, and the interesting part is
watching a capable model get told *no* and have to work inside the answer.

The real problem came from a game show I produce. It has a finite question deck
and a hard no-repeat rule — once a question airs, it is spent forever. Ask a
language model for five quiz questions and it will cheerfully hand you five it
already gave you last week. It has no idea what it has spent, because *it can't*.
That knowledge lives with the show, not the model.

## What it does

**Ladder** is a tiered question deck exposed to browser agents over WebMCP.

Every question is `available`, `reserved` (asked on camera, recording not yet
locked), or `burned` (locked, gone). A set is one question per difficulty rung.
From those two rules, everything follows:

- **Availability is per rung, not global.** A deck can be 90% full and still be
  empty at the one tier tonight needs. A total count calls that healthy. This
  doesn't — and that distinction is the difference between a working show and a
  host improvising at the table.
- **Builds are deterministic.** Same spec, same ledger, byte-identical set. Two
  people checking before a shoot see the same thing, and regenerating afterwards
  reproduces what was actually asked.
- **It refuses to under-fill.** No candidate for a rung raises an error *naming
  the rung*, rather than quietly returning four questions and letting you find
  out on the day.
- **A category can't give away its own answer.** The build fails if a category
  shares a discriminating word with the right option. This one came from a real
  card whose header read "Devil's Cut" above the answer "the devil's cut."

Four tools are registered on the page:

| tool | does |
|---|---|
| `deck_report` | what remains, per rung, and which rungs are exhausted |
| `theme_search` | coverage for a theme, and which rungs it cannot cover |
| `build_set` | a full set from a spec — deterministic, refuses to under-fill |
| `screen_candidates` | would any of these repeat something already used |

## Why this needs WebMCP

Two other approaches exist and both fail here.

**A general agent driving the DOM** can read the page, but it cannot know what is
burned. That state isn't rendered — it's a subtraction across a deck and a
ledger. The agent would have to reimplement the rules by scraping, and it would
get them wrong in the direction that costs a take: reading spent questions as
available.

**A server-side MCP server** knows the rules but loses the human. The whole point
is that a person and an agent are looking at the same deck at the same time,
watching the same rungs empty. Shared context is the feature.

WebMCP puts the rules **in the page, next to the human**. The agent gets tools
that encode the constraints, the person sees the same state update, and neither
can drift from the other — because they are the same four operations. The page
calls the same HTTP endpoints the agent does. There is deliberately no agent-only
back door.

That's the "impossible before" part, and it isn't about speed. It's that the site
gets to be an authority the agent has to respect.

## How I built it

- **Engine**: pure Python standard library. No runtime dependencies. 57 tests.
- **API**: Vercel Python serverless — four operations on one function.
- **Page**: no framework, no build step, and **no JavaScript required to read
  it**. Tools register via `document.modelContext.registerTool()` when an agent
  is present; without one the page still works and simply shows the deck.
- **Matching is fuzzy on purpose, and errs toward "already used."** Ledgers are
  hand-typed and paraphrase; decks carry full setups and smart quotes. Literal
  matching would read spent questions as available — an error in the direction
  that costs a take.

## Challenges

**The rate limit on my own certainty.** Early on the builder returned a *horse*
for a set that asked for dog questions. Both a Palomino question and a Great Dane
question matched — one on "breed", one on "dog" — and the tiebreak fell through
to a content hash. The fix was to make theme *order* meaningful. I only found it
by reading real output, not by writing more tests.

**Multiple-choice stems are generic.** "Which of these came first?" carries no
distinguishing words; they're all in the options. Matching on the stem alone
scored near zero, so a **burned** question read as available — the exact
repeat-on-camera failure, reached by the safest-looking possible parse.

**Difficulty is calibrated for a general audience.** A subject-matter expert
makes the bands wrong: a "hard" question about their own field is a gimme. Specs
can now shift the difficulty band per rung, which turned out to matter more than
any amount of extra questions.

## What I learned

The valuable thing was not the tools. It was discovering how many ways a system
can be **confidently wrong in the direction that costs you** — and that the fix
is almost always to make the failure loud and early rather than to make the
success cleverer.

## What's next

The deck in this repo is synthetic — 21 questions written for the submission. The
real one stays private, because publishing unaired questions would spoil the show
they belong to. That is itself the argument for why a no-repeat ledger has to
live somewhere other than a public repo, and why the tools have to enforce rules
the model can't see.

## Built with

`python` · `vercel` · `webmcp` · `document.modelContext` · no framework, no
dependencies, no build step

---

# Demo video — shot list (target 2:30, hard cap 3:00)

Record with audio. Screen capture is fine; no face needed.

| time | shot | say |
|---|---|---|
| 0:00–0:15 | the page, deck report visible | "Every agent demo is the agent doing things to a site. This is a site that tells the agent no." |
| 0:15–0:40 | scroll the rung counts | "Finite deck. Every question is available, reserved, or burned. One question per difficulty rung." |
| 0:40–1:20 | ask the agent to build a themed set | "It draws from what's left — and it cannot pick anything already used." |
| 1:20–1:50 | ask for a theme the deck can't cover | "Here's the part that matters. It tells you which rung it can't fill, a week before the shoot, instead of handing you four questions on the day." |
| 1:50–2:15 | `screen_candidates` catching a repeat | "And it checks proposed questions against everything already burned." |
| 2:15–2:30 | the page with no agent | "Same four operations the page itself uses. No agent-only back door — one implementation, nothing to drift." |

**Do not** open with architecture. Open with the refusal — it's the only thing in
the video a judge hasn't seen forty times.
