import random
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeout, Error as PlaywrightError

from bot.handlers.navigation import navigate_to, UnexpectedPageError


def backoff(attempt, base=1.0, cap=30.0):
    delay = min(base * (2 ** attempt), cap)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


def navigate_with_retry(page, url, expected_identity, reporter=None, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            navigate_to(page, url, expected_identity, reporter)
            return
        except (PlaywrightTimeout, PlaywrightError, UnexpectedPageError) as e:
            if reporter:
                reporter.log_event(
                    "navigate_retry",
                    outcome="retry",
                    retry=attempt,
                    detail=str(e),
                )
            if attempt == max_retries:
                raise
            delay = backoff(attempt)
            time.sleep(delay)
