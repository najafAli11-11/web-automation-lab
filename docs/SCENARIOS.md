# Scenario Coverage Matrix

The key deliverable. For each scenario: how the sandbox simulates it → how the bot
detects it → handling strategy → evidence (log excerpt or screenshot).

## Core scenarios

| # | Scenario | Sandbox simulation | Bot detection | Handling strategy | Evidence |
|---|----------|--------------------|---------------|-------------------|----------|
| 1 | Random pop-up / modal | Injects `#popup-overlay` modal markup into HTML via `after_request` hook | Global watcher checks for `#popup-overlay` selector before each action | Dismiss via close button (`#popup-close`), Escape key, or backdrop click; verify gone | _Pending bot implementation_ |
| 2 | Cookie / consent banner | Injects `#cookie-banner` markup on first visit via `after_request`; sets `cookie_consent` cookie to prevent re-show | Presence check at session start | Click `#accept-cookies` button; verify banner removed | _Pending bot implementation_ |
| 3 | Simulated captcha gate | `before_request` hook redirects to `/captcha-gate?target=<url>` when active; gate serves a math problem (two random numbers + sum) | Detect gate page by URL (`/captcha-gate`) or `#captcha-form` marker | Read the two numbers from the page, compute sum, submit via form; redirect back to target with `captcha_solved=1` flag | _Pending bot implementation_ |
| 4 | Site down / server errors | `before_request` hook returns 500/503 for a bounded window of requests (2 consecutive failures, then recovers) | Non-200 response / navigation failure | Exponential backoff + retry cap; resume from last completed item (checkpointing) | _Pending bot implementation_ |
| 5 | Slow responses / timeouts | `before_request` hook injects `time.sleep(2.0-5.0s)` delay before responding | Explicit waits hitting their timeout | Bounded per-action timeouts; distinguish slow (wait longer) from dead (→ scenario 4 path) | _Pending bot implementation_ |
| 6 | Unexpected redirection | `before_request` hook redirects to `/interstitial?target=<url>` when active; interstitial has a "Continue" link back to the target | Detect URL mismatch (on `/interstitial` instead of expected target) | Click the continue link to return to target; verify `detour_handled=1` flag prevents re-interception | _Pending bot implementation_ |
| 7 | DOM change / selector drift | Serves alternate templates (`listing_drift.html`, `detail_drift.html`) with different ids, class names, and element order | A selector resolves via fallback chain rather than the primary | Resilient selectors (text / ARIA role / attribute) with ordered fallback chains; all selectors centralized in `bot/selectors.py`; never depend on element order | _Pending bot implementation_ |
| 8 | Blocked / intercepted clicks | Injects a sticky `#click-block-overlay` element over key controls via `after_request` hook | Playwright reports click intercepted / element not actionable | Detect interception; dismiss overlay via `#overlay-dismiss` button or Escape key; verify the click took effect | _Pending bot implementation_ |

## Stretch scenarios

_Listed separately (see brief §2.3)._
