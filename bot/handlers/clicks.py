"""Click with intercept recovery (PLANNING §4, scenario 8 blocked_clicks).

Playwright's click() auto-waits for actionability, so an element covered by a
sticky overlay raises a TimeoutError rather than clicking through it. We catch
that, dismiss the overlay, and retry — distinguishing a recoverable block from
a genuine failure. `page` is a Playwright Page.
"""

from playwright.sync_api import TimeoutError as PlaywrightTimeout, Error as PlaywrightError

from bot.handlers.locate import first, is_present, LocateError
from bot.handlers.popups import ensure_clear
from bot import selectors as S


class ClickError(Exception):
    pass


def safe_click(page, selector_chain, reporter=None, max_retries=3, index=0):
    """Click a matching element, recovering from block overlays.

    Clicks the `index`-th element of the first selector in the chain that
    resolves (default the first element). On a click that can't land (element
    not actionable / intercepted) or a missing target, check for the blocking
    overlay; if found, dismiss it and retry. Raises ClickError once retries are
    exhausted. The actionability timeout is short (3s) so an intercepted click
    surfaces quickly and triggers overlay recovery instead of stalling."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            el = _locate(page, selector_chain, index)
            el.click(timeout=3000)
            return
        except (PlaywrightError, PlaywrightTimeout, LocateError) as e:
            last_err = e
            if is_present(page, S.BLOCK_OVERLAY, timeout=1):
                dismiss_block_overlay(page, reporter)
                if reporter:
                    reporter.log_event(
                        "safe_click", scenario="blocked_clicks",
                        strategy="dismiss_overlay",
                        outcome="resolved" if attempt < max_retries else "failed",
                        retry=attempt,
                    )
                continue
            if attempt == max_retries:
                raise ClickError(f"click failed after {max_retries} attempts: {e}")
    raise ClickError(f"click failed after {max_retries} attempts: {last_err}")


def _locate(page, selector_chain, index):
    """Resolve the index-th element of the first matching selector.

    index 0 is the common case (first()). For index > 0 we take the nth match
    of the first selector that has enough elements, waiting for it to be
    visible so the click auto-wait behaves like first()'s."""
    if index == 0:
        return first(page, selector_chain, state="clickable")
    for sel in selector_chain:
        loc = page.locator(sel)
        if loc.count() > index:
            nth = loc.nth(index)
            nth.wait_for(state="visible", timeout=5000)
            return nth
    raise LocateError(f"no selector in {selector_chain} has index {index}")


def dismiss_block_overlay(page, reporter=None):
    """Remove the sticky click-blocking overlay via its close button, falling
    back to Escape (the overlay listens for both). The popup modal is z-indexed
    above the block overlay, so clear any popup/cookie overlay first — otherwise
    it intercepts the dismiss-button click too."""
    ensure_clear(page, reporter)
    if is_present(page, S.BLOCK_DISMISS, timeout=1):
        first(page, S.BLOCK_DISMISS).click(timeout=3000)
    else:
        page.keyboard.press("Escape")
