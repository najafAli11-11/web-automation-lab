"""Entry point: crawl the marketplace and extract every item (PLANNING §1, §4).

Walks every listing page, visits each item's detail page, extracts and validates
the fields, and writes clean structured data to results.json. Interactions go
through the browser like a human — clicking item links and the pagination "Next"
control (exercising scenario 8 blocked_clicks via safe_click) rather than only
navigating by URL — with URL-based navigation kept as the recovery path. Each
click is followed by detour resolution (captcha/interstitial) and checkpointing
by item id so a mid-crawl failure resumes instead of restarting or duplicating.
Interacts with the site only through the browser (decoupling contract §2.4).
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError

from bot.handlers.locate import first, all_matches, is_present, LocateError
from bot.handlers.popups import ensure_clear
from bot.handlers.navigation import identify, resolve_to, UnexpectedPageError
from bot.handlers.network import navigate_with_retry
from bot.handlers.clicks import safe_click, ClickError
from bot.reporting import Reporter
from bot import selectors as S


def try_navigate(page, url, expected_identity, reporter):
    """Navigate with retry, escalating instead of crashing when retries exhaust.

    navigate_with_retry backs off and retries a bounded number of times, then
    re-raises if the site is still unreachable (e.g. a server_errors window
    longer than the retry cap). Per PLANNING §4 the crawl must not restart from
    scratch on that: we screenshot the unexpected state, log it, and return
    False so the caller can skip this item/page and press on — checkpointing by
    id (seen_ids) means already-extracted items are never re-fetched. Returns
    True on success."""
    try:
        navigate_with_retry(page, url, expected_identity, reporter)
        return True
    except (PlaywrightTimeout, PlaywrightError, UnexpectedPageError) as e:
        reporter.screenshot(page, f"nav_failed_{expected_identity}")
        reporter.log_event(
            "navigate", strategy="retry_exhausted", outcome="escalated",
            detail={"url": url, "expected": expected_identity, "error": str(e)},
        )
        return False


def extract_detail(page):
    """Read every field from the current detail page into a dict.

    Title comes from the heading; the rest from the DETAIL_FIELDS chains.
    Price has its currency symbol stripped so downstream data is numeric-clean."""
    fields = {"title": first(page, S.DETAIL_TITLE).inner_text().strip()}
    for field_name, selectors in S.DETAIL_FIELDS.items():
        raw = first(page, selectors).inner_text().strip()
        if field_name == "price":
            raw = raw.replace("$", "").strip()
        fields[field_name] = raw
    return fields


def collect_item_hrefs(page):
    """Return the detail-page hrefs for every item on the current listing page.

    Hrefs are read up front so we never hold locators across a navigation
    (which would go stale under dom_drift / re-render)."""
    try:
        items = all_matches(page, S.LISTING_ITEM)
    except LocateError:
        return []
    hrefs = []
    for item_el in items:
        link = first(item_el, S.ITEM_LINK, state="attached")
        href = link.get_attribute("href")
        if href:
            hrefs.append(href)
    return hrefs


def crawl(base_url, run_dir, seed=None):
    reporter = Reporter(run_dir)
    if seed is not None:
        reporter.set_seed(seed)

    results = []
    seen_ids = set()

    with sync_playwright() as pw:
        # --disable-dev-shm-usage avoids renderer crashes from a small /dev/shm
        # when pages carry large inline images (the captcha tiles).
        browser = pw.chromium.launch(
            headless=False,  # headless=False to see the browser for debugging
            args=["--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        try:
            page_num = 1
            while True:
                listing_url = f"{base_url}/?page={page_num}"
                if not try_navigate(page, listing_url, "listing", reporter):
                    break  # listing page unreachable after retries — stop cleanly
                ensure_clear(page, reporter)

                hrefs = collect_item_hrefs(page)
                if not hrefs:
                    break

                for i, href in enumerate(hrefs):
                    detail_url = href if href.startswith("http") else f"{base_url}{href}"
                    # Click the item link like a user (exercises blocked_clicks),
                    # then resolve any captcha/interstitial the click triggered.
                    # If the click can't land (ClickError/LocateError) or the
                    # click landed on an error/unknown page (UnexpectedPageError,
                    # e.g. a server_errors 5xx), fall back to direct navigation
                    # with backoff/retry rather than crashing the crawl.
                    try:
                        safe_click(page, S.ITEM_LINK, reporter, index=i)
                        resolve_to(page, "detail", reporter, target_url=detail_url)
                    except (ClickError, LocateError, UnexpectedPageError):
                        if not try_navigate(page, detail_url, "detail", reporter):
                            continue  # this item unreachable — skip, resume next
                    ensure_clear(page, reporter)

                    if identify(page) != "detail":
                        reporter.screenshot(page, f"unexpected_detail_page{page_num}")
                    else:
                        item = extract_detail(page)
                        item_id = item.get("id")
                        if item_id not in seen_ids:  # checkpoint/dedupe (scenario 4)
                            seen_ids.add(item_id)
                            results.append(item)
                            reporter.log_item_extracted(item)

                    # Return to this listing page before the next item click so
                    # the item links are present to click again.
                    if not try_navigate(page, listing_url, "listing", reporter):
                        break
                    ensure_clear(page, reporter)

                # Click the pagination "Next" link to advance pages (exercises
                # blocked_clicks), resolving any detour; fall back to a direct
                # navigation if the click cannot land.
                if not is_present(page, S.PAGINATION_NEXT, timeout=2):
                    break
                try:
                    safe_click(page, S.PAGINATION_NEXT, reporter)
                    resolve_to(page, "listing", reporter,
                               target_url=f"{base_url}/?page={page_num + 1}")
                except (ClickError, LocateError, UnexpectedPageError):
                    if not try_navigate(
                        page, f"{base_url}/?page={page_num + 1}", "listing", reporter):
                        break
                page_num += 1
        finally:
            browser.close()

    out_path = Path(run_dir) / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {out_path}")

    reporter.summary()
    reporter.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Resilient bot for Retro Game Marketplace")
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--run-dir", default="runs/latest")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    crawl(args.base_url, args.run_dir, seed=args.seed)


if __name__ == "__main__":
    main()
