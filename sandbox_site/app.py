"""Flask sandbox server for the Resilient Web Automation Lab.

Serves a paginated listing page and per-item detail pages, rendering
retro-game data from data/items.json.

The chaos engine (see docs/PLANNING.md §3) lives entirely on this side.
A before_request hook reads chaos.json fresh on every request and decides
which disruption scenarios apply; response-level effects (500/503) run in
that hook, content-level effects (modal, cookie banner) are injected in an
after_request hook. The bot never reads chaos.json — it only sees the
resulting HTML/status like a human would.
"""

import json
import math
import random
from pathlib import Path

from flask import Flask, abort, g, render_template, request

app = Flask(__name__)

_HERE = Path(__file__).resolve().parent
# Data lives next to this file, in data/items.json.
DATA_PATH = _HERE / "data" / "items.json"
CHAOS_PATH = _HERE / "chaos.json"
PER_PAGE = 8

# All scenario keys the engine knows about (matches chaos.json). Scenarios
# not yet implemented are still parsed/decided so the config stays honest;
# only the three below actually have effects wired in for now.
SCENARIO_KEYS = [
    "popup_modal", "cookie_banner", "captcha_gate", "server_errors",
    "slow_responses", "unexpected_redirect", "dom_drift", "blocked_clicks",
]

# server_errors "request window": how many consecutive requests fail once the
# window opens, and the status codes cycled through.
SERVER_ERROR_WINDOW = 2
SERVER_ERROR_CODES = [503, 500]

# Monotonic request counter. Drives both the seeded PRNG (so random mode is
# reproducible and advances per request) and the server-error window.
_request_seq = 0


def load_items():
    """Read and return the list of items from items.json.

    Read on each request so edits to the dataset show up without a
    restart. The file is small, so the cost is negligible.
    """
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_chaos():
    """Read chaos.json fresh. Returns a safe default if missing/invalid so a
    bad edit disables chaos rather than crashing the whole site."""
    try:
        with open(CHAOS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"random_mode": False, "seed": 0, "scenarios": {}}
    cfg.setdefault("random_mode", False)
    cfg.setdefault("seed", 0)
    cfg.setdefault("scenarios", {})
    return cfg


def decide_scenarios(cfg, seq):
    """Return the set of scenario keys active for this request.

    Deterministic mode: a scenario is active iff enabled is true.
    Random mode: a seeded PRNG decides per scenario using probability.
    The PRNG is re-seeded from (seed, seq) each request so the same seed
    replays an identical sequence of requests.
    """
    scenarios = cfg.get("scenarios", {})
    if not cfg.get("random_mode"):
        return {k for k in SCENARIO_KEYS
                if scenarios.get(k, {}).get("enabled")}

    # Deterministic per-request PRNG: combine seed and sequence number into
    # a single int seed so the same base seed replays an identical run.
    rng = random.Random(cfg.get("seed", 0) * 1_000_003 + seq)
    active = set()
    for k in SCENARIO_KEYS:
        prob = scenarios.get(k, {}).get("probability", 0.0)
        if rng.random() < prob:
            active.add(k)
    return active


@app.before_request
def apply_chaos():
    """Decide active scenarios for this request and apply response-level
    effects. Content-level effects are applied later in after_request."""
    global _request_seq
    # Only chaos-decorate real pages; skip static assets so CSS still loads.
    if request.path.startswith("/static/"):
        g.chaos = set()
        return None

    _request_seq += 1
    seq = _request_seq
    cfg = load_chaos()
    active = decide_scenarios(cfg, seq)
    g.chaos = active

    # server_errors: fail for a bounded window of requests, then recover.
    # The window is keyed off the request counter so it is reproducible and
    # self-heals (the bot must back off and retry, not give up).
    if "server_errors" in active:
        if seq % (SERVER_ERROR_WINDOW + 2) < SERVER_ERROR_WINDOW:
            code = SERVER_ERROR_CODES[seq % len(SERVER_ERROR_CODES)]
            abort(code)

    return None


def _cookie_banner_html():
    return (
        '<div id="cookie-banner" class="cookie-banner" role="dialog" '
        'aria-label="cookie consent">'
        "<span>We use cookies to make this retro shop work. </span>"
        '<button id="accept-cookies" class="accept-cookies">Accept</button>'
        "</div>"
    )


def _popup_modal_html():
    return (
        '<div id="popup-overlay" class="modal-overlay">'
        '<div id="popup-modal" class="modal" role="dialog" '
        'aria-label="newsletter">'
        "<h2>Join the mailing list!</h2>"
        "<p>Get restock alerts for rare carts.</p>"
        '<button id="popup-close" class="modal-close" '
        'aria-label="close">&times;</button>'
        "</div></div>"
    )


@app.after_request
def inject_content_chaos(response):
    """Inject content-level disruptions (modal, cookie banner) into HTML
    responses just before the closing </body>. Non-HTML responses (static
    files, redirects, errors) are passed through untouched."""
    active = getattr(g, "chaos", set())
    if not active:
        return response
    ctype = response.headers.get("Content-Type", "")
    if "text/html" not in ctype:
        return response

    injections = ""
    if "popup_modal" in active:
        injections += _popup_modal_html()

    # cookie_banner only on "first visit": show it until the browser has the
    # cookie_consent cookie, then set the cookie so it does not reappear.
    if "cookie_banner" in active and not request.cookies.get("cookie_consent"):
        injections += _cookie_banner_html()
        response.set_cookie("cookie_consent", "shown", max_age=3600)

    if not injections:
        return response

    html = response.get_data(as_text=True)
    if "</body>" in html:
        html = html.replace("</body>", injections + "</body>", 1)
    else:
        html += injections
    response.set_data(html)
    return response


@app.route("/")
def listing():
    """Paginated listing page. Page selected via ?page=N (1-indexed)."""
    items = load_items()
    total_pages = max(1, math.ceil(len(items) / PER_PAGE))

    # Clamp the requested page into [1, total_pages]; fall back to 1 on
    # anything non-numeric.
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    start = (page - 1) * PER_PAGE
    page_items = items[start:start + PER_PAGE]

    return render_template(
        "listing.html",
        items=page_items,
        page=page,
        total_pages=total_pages,
        total_items=len(items),
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@app.route("/item/<int:item_id>")
def detail(item_id):
    """Detail page for a single item, showing every field."""
    items = load_items()
    item = next((i for i in items if i.get("id") == item_id), None)
    if item is None:
        abort(404)
    return render_template("detail.html", item=item)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
