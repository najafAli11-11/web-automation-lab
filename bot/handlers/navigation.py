"""Navigation with detour recovery (PLANNING §4, scenarios 3 & 6).

Navigate once, then follow whatever detour the site inserts — clicking through
an interstitial (unexpected_redirect) or solving the captcha gate — until the
intended page is reached. A 5xx response or an unrecognised page raises
UnexpectedPageError so the caller (navigate_with_retry) can back off and retry.
No fixed sleeps: each detour performs its own navigation and we wait on load
state, never a timer. `page` is a Playwright Page.
"""

from bot.handlers.locate import is_present, first
from bot.handlers.captcha import solve as solve_captcha
from bot import selectors as S


class UnexpectedPageError(Exception):
    def __init__(self, current, expected):
        self.current = current
        self.expected = expected
        super().__init__(f"expected {expected} page, got {current}")


def identify(page):
    """Return the identity of the current page, or None if unrecognised.

    Uses a short per-check timeout: after a completed navigation the expected
    element is already in the DOM and resolves instantly, so only genuine
    misses pay the timeout (kept at 1s to keep multi-identity checks cheap)."""
    for name, selectors in S.PAGE_IDENTITY.items():
        if is_present(page, selectors, timeout=1):
            return name
    return None


def navigate_to(page, url, expected_identity, reporter=None):
    """Navigate to `url` and resolve any detours until `expected_identity`."""
    resp = page.goto(url)
    if resp is not None and resp.status >= 500:
        raise UnexpectedPageError(current=f"http_{resp.status}", expected=expected_identity)
    resolve_to(page, expected_identity, reporter, target_url=url)


def resolve_to(page, expected_identity, reporter=None, target_url=None):
    """Follow detours on the *current* page until `expected_identity` is shown.

    Used both after a goto (navigate_to) and after a click that triggers its own
    navigation (e.g. pagination), so a captcha/interstitial inserted on either
    path is resolved in place. Raises UnexpectedPageError if the page can't be
    resolved to the expected identity within a bounded number of detours."""
    for _ in range(5):
        identity = identify(page)
        if identity == expected_identity:
            return

        if identity == "interstitial":
            if reporter:
                reporter.log_event(
                    "navigate", scenario="unexpected_redirect",
                    strategy="click_continue", outcome="resolved",
                    detail={"target_url": target_url},
                )
            first(page, S.INTERSTITIAL_CONTINUE).click()
            page.wait_for_load_state()
            continue

        if identity == "captcha":
            if reporter:
                reporter.log_event(
                    "navigate", scenario="captcha_gate",
                    strategy="solve", outcome="in_progress",
                    detail={"target_url": target_url},
                )
            solve_captcha(page, reporter)
            page.wait_for_load_state()
            continue

        raise UnexpectedPageError(current=identity, expected=expected_identity)

    raise UnexpectedPageError(current=identify(page), expected=expected_identity)
