# PLANNING — Resilient Web Automation Lab

**Project:** Retro Video Games Marketplace — sandbox site + resilient Playwright bot
**Stack:** Flask (Python) sandbox · Playwright Python (sync API) bot · pytest
**Author:** _me_ · **Status:** week 1 planning (pre-code)

---

## 1. Spec summary

Build two decoupled pieces in one repo:

1. **Sandbox site** (`sandbox_site/`) — a small Flask server rendering a retro-game
   listings marketplace from a local JSON file, with a **chaos engine** that can inject
   real-world disruptions on demand (per-scenario toggles) or randomly (seeded).
2. **Automation bot** (`bot/`) — a Playwright bot that crawls the whole catalog,
   extracts every item, and saves clean structured data — and keeps succeeding when
   the chaos engine is turned on.

The bot is the star. The site is only the lab rig. **Appearance earns zero marks** —
unstyled HTML throughout.

### Decoupling contract (hard rule, brief §2.4)
The bot interacts with the site **only through the browser**, like a human:
- No reading `data/items.json` directly.
- No hidden/backdoor endpoints that reveal answers.
- No shared code between site and bot that leaks selectors or data.
- The bot's only inputs are the base URL and its own config. The `chaos.json` file is
  the *site's* config; the bot must never read it to "know" what's coming.

### Bot workflow (the happy path, chaos off)
1. Open the listing page.
2. Walk every numbered page (`?page=N`) via next/pagination links until exhausted.
3. Visit each item's detail page.
4. Extract all fields.
5. Save to `runs/results.json` (clean, validated).
6. Print a run summary.

### Data model — retro game item
| field | type | notes |
|-------|------|-------|
| `id` | int/string | stable unique key; used to verify completeness |
| `title` | string | e.g. "The Legend of Zelda: Ocarina of Time" |
| `platform` | string | N64, SNES, PS1, Genesis, Game Boy, … |
| `price` | number | USD, 2 decimals |
| `year` | int | release year, 1980–2005ish |
| `condition` | enum | `sealed` / `CIB` / `loose` |
| `region` | enum | `NTSC` / `PAL` / `NTSC-J` |
| `description` | string | 1–2 sentences |

**Dataset:** 20–40 items, AI-generated (not hand-written), in `sandbox_site/data/items.json`.
Listing paginated at ~8 items/page → ~3–5 pages.

### Success definition
- Chaos **off**: bot extracts all N items, every field present and well-typed.
- Chaos **on** (each scenario, and random gauntlet): same complete, correct result —
  bot never hangs forever, never crashes with an unhandled exception; every disruption
  is logged, screenshotted, and reported.

---

## 2. Scenario list

For each scenario the demo loop is: **toggle in `chaos.json` → bot detects → bot recovers
→ visible in log + run summary.** Full detection/handling/evidence detail lives in
`docs/SCENARIOS.md` (the graded matrix); this section is the design intent.

### Core scenarios (all 8 required)

| # | Scenario | Sandbox simulates | Bot detects by | Handling strategy |
|---|----------|-------------------|----------------|-------------------|
| 1 | **Random pop-up / modal** | Injects a newsletter/promo modal overlay into the HTML at a random moment | A global watcher checks for known modal selectors before each action | Dismiss (close button / ESC) whenever seen; verify gone; then continue |
| 2 | **Cookie / consent banner** | Renders a consent banner overlay on first visit | Presence check at session start | Accept/dismiss once before the workflow starts; verify removed |
| 3 | **Simulated captcha gate** | Serves a fake gate page (two numbers + "what's the sum?") that interrupts navigation | Detect gate page identity (URL/marker element) instead of expected page | **Solve programmatically**: read the two numbers, compute sum, submit, resume from the interrupted step. (Simulated only — never a real captcha.) |
| 4 | **Site down / server errors** | Randomly returns 500/503 (or refuses) for a window | Non-200 response / navigation failure | Exponential backoff + retry cap; **resume from last completed item**, not from scratch (checkpointing) |
| 5 | **Slow responses / timeouts** | Random multi-second delay before responding | Explicit waits hitting their timeout | Sane per-action timeouts + waits (never fixed `sleep`); distinguish *slow* (wait longer, bounded) from *dead* (→ scenario 4 path) |
| 6 | **Unexpected redirection** | Navigation randomly lands on a promo/interstitial page instead of target | Verify URL + page-identity marker after every navigation | Detect the detour; route back to the intended URL; re-verify before proceeding |
| 7 | **DOM change / selector drift** | Serves an alternate layout: different **ids, class names, and element order** for the same content | A selector resolves via fallback chain rather than the primary | Resilient selectors (text / ARIA role / attribute) with ordered fallback chains; all selectors centralized in `bot/selectors.py`; never depend on element order |
| 8 | **Blocked / intercepted clicks** | An overlay / sticky banner / misplaced element sits over the target control | Playwright reports click intercepted / element not actionable | Detect interception; remove/scroll past obstruction (or dismiss the overlaying modal) or use a safe alternative; **verify the click took effect** |

### Stretch scenarios (week 4 only — NOT part of core plan)
Attempted only after all 8 core pass the gauntlet repeatedly:
- Session/state expiry mid-run → re-establish session, resume.
- Pagination switching to "load more" / infinite scroll → detect mode, adapt crawl.
- Stale element references → re-locate on `StaleElement`-style failures.
- Random logout / "session timed out" page → detect, recover.
- Data-integrity: duplicate or missing items in listings → dedupe by `id`, detect gaps.
- Rate-limit (HTTP 429) → obey `Retry-After`, slow down.
- **Own invention (top-marks target):** _TBD in week 4_ — candidate: randomized field
  scrambling (price shown in a different currency/format) forcing normalization on extract.

---

## 3. Chaos-engine design

### Goals
- Every scenario **reproducibly triggerable** on demand (deterministic).
- A **random mode** with per-scenario probability + a single **seed** for realistic,
  repeatable end-to-end gauntlet runs.
- Lives entirely on the **site** side. The bot never reads it.

### `chaos.json` shape
```json
{
  "random_mode": false,
  "seed": 1234,
  "scenarios": {
    "popup_modal":         { "enabled": false, "probability": 0.3 },
    "cookie_banner":       { "enabled": false, "probability": 1.0 },
    "captcha_gate":        { "enabled": false, "probability": 0.2 },
    "server_errors":       { "enabled": false, "probability": 0.2 },
    "slow_responses":      { "enabled": false, "probability": 0.3 },
    "unexpected_redirect": { "enabled": false, "probability": 0.2 },
    "dom_drift":           { "enabled": false, "probability": 0.4 },
    "blocked_clicks":      { "enabled": false, "probability": 0.3 }
  }
}
```

### Two modes
- **Deterministic (default):** a scenario fires **iff** `enabled: true`. Used for
  per-scenario demos and per-scenario tests — 100% reproducible, no randomness.
- **Random mode (`random_mode: true`):** on each request, a seeded PRNG decides per
  scenario whether it fires, using `probability`. Same `seed` ⇒ identical run ⇒ the
  gauntlet is reproducible.

### Implementation sketch
- A Flask **middleware / `before_request` hook** reads `chaos.json` fresh each request
  (so toggling doesn't need a restart) and decides which disruptions apply to this request.
- Seeded PRNG (`random.Random(seed)`), advanced deterministically per request so a fixed
  seed replays identically.
- Response-level effects (500/503, delay, redirect) handled in the hook; content-level
  effects (inject modal/banner, swap layout, insert captcha gate) handled in the
  template-rendering path.
- Scenario → mechanism:
  - `popup_modal`, `cookie_banner` → inject overlay markup into rendered HTML.
  - `captcha_gate` → intercept a navigation and serve the gate template instead.
  - `server_errors` → return 500/503 for a request window.
  - `slow_responses` → `time.sleep(delay)` before responding (server side — the bot must
    still never use fixed sleeps).
  - `unexpected_redirect` → 302 to an interstitial route.
  - `dom_drift` → render an alternate template variant (different ids/classes/order).
  - `blocked_clicks` → inject a sticky/overlay element over key controls.

---

## 4. Bot architecture

```
bot/
├── run.py         # entry point: orchestrates the crawl-and-extract workflow
├── selectors.py   # ALL selectors + ordered fallback chains, one place (scenario 7)
├── reporting.py   # structured logging, screenshots, run summary
└── handlers/      # one module per disruption concern
    ├── popups.py        # modal + cookie-banner watcher/dismisser (1, 2)
    ├── captcha.py       # detect + solve math gate (3)
    ├── network.py       # retry/backoff + checkpoint resume (4), slow-vs-dead (5)
    ├── navigation.py    # post-nav URL/identity verify + reroute (6)
    ├── locate.py        # resilient locate via selectors.py fallback chains (7)
    └── clicks.py        # safe-click: detect interception, clear, verify (8)
```

### Core design principles
- **Detect → decide → act → verify.** Every handler confirms recovery worked
  (banner gone, on the right URL, click registered) before returning control.
- **Global watchers, not one-off checks.** Modals/banners can appear at any time, so a
  `ensure_clear()` guard runs before every significant interaction — not just at start.
- **Checkpointing.** The workflow tracks the last successfully extracted item `id`, so a
  server-error retry resumes there instead of restarting the crawl.
- **Selectors centralized.** Nothing outside `selectors.py` hard-codes a CSS path. Each
  logical element has an ordered fallback chain (role → text → attribute → css) so
  `dom_drift` can't break it.
- **No fixed sleeps, ever.** Only Playwright explicit waits with bounded timeouts.
  Distinguish "slow" (wait, bounded) from "dead" (fail → backoff/retry).
- **Fail loud, not silent.** Handlers catch *specific* expected exceptions
  (`TimeoutError`, navigation errors, click-intercepted), log everything, and never
  blanket-`except: pass`. Unknown states → screenshot + escalate.

### Reporting (`reporting.py`)
- **Structured log** (JSONL) of every event: action, scenario detected, strategy taken,
  retry count, outcome, timestamp.
- **Auto screenshot** on any unexpected state, saved under `runs/`.
- **Run summary** at the end: items processed vs expected, disruptions encountered +
  how each was resolved, total retries, and a **data completeness/correctness verdict**.

### Retry/backoff (pure, unit-testable)
Exponential backoff with cap and jitter, as a pure function → tested in isolation
(`base * 2**attempt`, capped, `attempt < max_retries`).

---

## 5. Testing plan (see brief §5)
- **Scenario tests (centerpiece):** per core scenario — start sandbox with that scenario
  forced `enabled`, run the bot (or its handler), assert the workflow still completes with
  correct data.
- **Unit tests (pure logic):** backoff calculator, selector-fallback resolution, extracted
  item validation, run-summary generation.
- **Chaos gauntlet:** one command runs the full workflow in `random_mode` with a fixed
  seed and asserts a complete, correct result.
- One documented command runs everything (`pytest`), fully local/offline.
- Habit: a new failure mode → first make it reproducible via chaos + a test, then fix it.

---

## 6. Risks & mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Silent-swallow handlers hide real bugs | Tests pass but bot is broken | Catch only specific exceptions; log all; screenshot unknown states; tests assert real extracted data, not just "no crash" |
| Fixed `sleep()` creeping in for "slow responses" | Flaky, slow, brittle bot | Ban fixed sleeps in review; use Playwright explicit waits only; slow-vs-dead logic in `network.py` |
| Brittle selectors break under DOM drift | Scenario 7 fails intermittently | Centralize in `selectors.py`; role/text/attribute fallback chains; never rely on element order |
| Modal/banner appears *mid-action*, not at start | Intermittent click failures | Global `ensure_clear()` watcher before every interaction, not one-time |
| Retry from scratch on server errors | Slow, may never finish, duplicate data | Checkpoint last completed `id`; resume there; dedupe by `id` |
| Random-mode non-reproducibility | Can't reproduce a gauntlet failure | Single seed drives a `random.Random`; log the seed in every run summary |
| Bot accidentally coupled to site internals | Violates §2.4; disqualifying | Decoupling contract in §1; bot only gets base URL; never reads `items.json`/`chaos.json` |
| Scope creep (fancy CSS, extra workflows) | Week 1 leaks into week 2; core slips | Appearance = 0 marks; "contact seller" action is a **non-goal/stretch**; depth over breadth |
| AI-invented Playwright methods / mixed async+sync | Code that looks right, fails at runtime | Verify every change against official Playwright docs; run immediately; commit only code I can explain line by line |
| Leaving core work for week 4 | No buffer, missed deadline | 8 core done by end of week 3; week 4 = stretch/polish/demo only |

### Non-goals (explicit)
- No styling/CSS beyond bare readability.
- No database, login, or framework beyond tiny Flask.
- No "contact seller"/cart action in the core (stretch at most).
- No cloud, no paid services, no API keys — everything local and free.
- No touching real third-party sites; captcha is simulated; no bypassing real anti-bot defenses.
