"""Dismiss popups and cookie banners (PLANNING §2 scenarios 1 & 2).

The `ensure_clear` watcher runs before every interaction so a modal or banner
that appears mid-workflow is cleared and verified gone, never worked around.
No fixed sleeps: dismissal is verified by a short bounded presence check.
`page` is a Playwright Page.
"""

from bot.handlers.locate import first, is_present
from bot import selectors as S


def dismiss_popup(page):
    """Dismiss the newsletter modal if present; return True if it was cleared.

    Prefers the modal's own close button, falling back to Escape (the modal
    listens for both). The close button is targeted so it clears only the
    modal — Escape is a page-wide key that other overlays (the blocked_clicks
    overlay) also listen for, so using it first would incidentally tear down an
    unrelated obstruction and rob its handler of the chance to detect it.
    Verifies the overlay is gone before reporting success."""
    if not is_present(page, S.POPUP_OVERLAY):
        return False
    if is_present(page, S.POPUP_CLOSE, timeout=1):
        first(page, S.POPUP_CLOSE).click()
        if not is_present(page, S.POPUP_OVERLAY, timeout=1):
            return True
    page.keyboard.press("Escape")
    return not is_present(page, S.POPUP_OVERLAY, timeout=1)


def dismiss_cookie_banner(page):
    """Accept the cookie banner if present; return True if it was cleared.

    Accepting sets a server-side cookie so it does not reappear (PLANNING §2
    scenario 2). Verifies the banner is gone before reporting success."""
    if not is_present(page, S.COOKIE_BANNER):
        return False
    first(page, S.COOKIE_ACCEPT).click()
    return not is_present(page, S.COOKIE_BANNER, timeout=1)


def ensure_clear(page, reporter=None):
    """Clear any popup/cookie obstruction before the caller interacts.

    Idempotent: does nothing (and reports nothing) when the page is already
    clear. Returns the list of obstructions actually dismissed."""
    actions = []
    if dismiss_popup(page):
        if reporter:
            reporter.log_event("ensure_clear", scenario="popup_modal", strategy="dismiss", outcome="resolved")
        actions.append("popup")
    if dismiss_cookie_banner(page):
        if reporter:
            reporter.log_event("ensure_clear", scenario="cookie_banner", strategy="accept", outcome="resolved")
        actions.append("cookie_banner")
    return actions
