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

import base64
import io
import json
import math
import random
import time
from math import cos, sin, radians
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from flask import Flask, abort, g, redirect, render_template, request, session
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
app.secret_key = "sandbox-captcha-secret-2026"

_HERE = Path(__file__).resolve().parent
# Data lives next to this file, in data/items.json.
DATA_PATH = _HERE / "data" / "items.json"
CHAOS_PATH = _HERE / "chaos.json"
PER_PAGE = 8

# All scenario keys the engine knows about (matches chaos.json). Scenarios
# not yet implemented are still parsed/decided so the config stays honest;
# only the five below actually have effects wired in for now.
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
    with open(DATA_PATH, encoding="utf-8-sig") as f:
        return json.load(f)


def load_chaos():
    """Read chaos.json fresh. Returns a safe default if missing/invalid so a
    bad edit disables chaos rather than crashing the whole site."""
    try:
        with open(CHAOS_PATH, encoding="utf-8-sig") as f:
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
    # /favicon.ico is skipped too: browsers auto-fetch it, and routing it
    # through the captcha gate would re-render a different grid and clobber
    # session["correct_indices"], rejecting the correct answer for the grid
    # the user actually sees.
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        g.chaos = set()
        return None

    _request_seq += 1
    seq = _request_seq
    g._request_seq = seq
    cfg = load_chaos()
    active = decide_scenarios(cfg, seq)
    g.chaos = active

    # server_errors: fail for a bounded window of requests, then recover.
    # The window is keyed off the request counter so it is reproducible and
    # self-heals (the bot must back off and retry, not give up).
    # Uses (seq-1) so the pattern is always 2 errors → 2 OK from seq=1.
    if "server_errors" in active:
        if (seq - 1) % (SERVER_ERROR_WINDOW + 2) < SERVER_ERROR_WINDOW:
            code = SERVER_ERROR_CODES[(seq - 1) % len(SERVER_ERROR_CODES)]
            abort(code)

    # slow_responses: inject a random multi-second delay before responding.
    # The bot must distinguish "slow" (wait longer, bounded) from "dead"
    # (server_errors path). Delay is 2-5 seconds, deterministic per request.
    if "slow_responses" in active:
        rng = random.Random(cfg.get("seed", 0) * 1_000_003 + seq)
        delay = rng.uniform(2.0, 5.0)
        time.sleep(delay)

    # captcha_gate: intercept navigation and serve a gate page instead.
    # The gate presents a simple math problem; solving it redirects back to
    # the original target URL (stored in the session).
    # Skip if we're already on the gate route (avoid infinite recursion) or
    # if the user just solved it (captcha_solved flag).
    if "captcha_gate" in active and request.path != "/captcha-gate" and not request.args.get("captcha_solved"):
        target = request.full_path if request.query_string else request.path
        gate_url = f"/captcha-gate?target={target}"
        return redirect(gate_url)

    # unexpected_redirect: navigation randomly lands on a promo/interstitial
    # page instead of the target. The bot must detect the detour and route
    # back to the intended URL. Skip if already on the interstitial route
    # (avoid infinite recursion) or if the user came from the interstitial
    # (detour_handled flag).
    if "unexpected_redirect" in active and request.path != "/interstitial" and not request.args.get("detour_handled"):
        target = request.full_path if request.query_string else request.path
        interstitial_url = f"/interstitial?target={target}"
        return redirect(interstitial_url)

    # dom_drift: flag set so routes can switch to alternate templates.
    g.dom_drift = "dom_drift" in active

    return None


def _cookie_banner_html():
    # Accept removes the banner client-side. The server also sets a
    # cookie_consent cookie (see inject_content_chaos), so it will not
    # reappear on the next request either. Plan §2 scenario 2:
    # "Accept/dismiss once before the workflow starts; verify removed."
    return (
        '<div id="cookie-banner" class="cookie-banner" role="dialog" '
        'aria-label="cookie consent">'
        "<span>We use cookies to make this retro shop work. </span>"
        '<button id="accept-cookies" class="accept-cookies">Accept</button>'
        "</div>"
        "<script>(function(){"
        "var b=document.getElementById('cookie-banner');"
        "var a=document.getElementById('accept-cookies');"
        "if(a){a.addEventListener('click',function(){if(b)b.remove();});}"
        "})();</script>"
    )


def _popup_modal_html():
    # Dismissable via the close button OR the Escape key OR clicking the
    # dimmed backdrop. Plan §2 scenario 1: "Dismiss (close button / ESC)
    # whenever seen; verify gone; then continue." A modal is a real
    # obstacle but always clearable through normal interaction (that is
    # what distinguishes it from scenario 8 blocked_clicks).
    return (
        '<div id="popup-overlay" class="modal-overlay">'
        '<div id="popup-modal" class="modal" role="dialog" '
        'aria-label="newsletter">'
        "<h2>Join the mailing list!</h2>"
        "<p>Get restock alerts for rare carts.</p>"
        '<button id="popup-close" class="modal-close" '
        'aria-label="close">&times;</button>'
        "</div></div>"
        "<script>(function(){"
        "var o=document.getElementById('popup-overlay');"
        "if(!o)return;"
        "function close(){o.remove();"
        "document.removeEventListener('keydown',onKey);}"
        "function onKey(e){if(e.key==='Escape')close();}"
        "var c=document.getElementById('popup-close');"
        "if(c)c.addEventListener('click',close);"
        "o.addEventListener('click',function(e){if(e.target===o)close();});"
        "document.addEventListener('keydown',onKey);"
        "})();</script>"
    )


def _blocked_clicks_html():
    # Injects a sticky overlay over key controls (pagination links,
    # item links). The bot must detect the overlay (click intercepted),
    # dismiss it via the close button or Escape key, then retry the
    # action. The overlay is injected just before </body> like the
    # other content-level chaos.
    return (
        '<div id="click-block-overlay" class="overlay-block" role="presentation">'
        '<div class="overlay-sticky">'
        '<span>Tip: Browse our featured collections!</span>'
        '<button id="overlay-dismiss" class="overlay-close">&times;</button>'
        '</div>'
        '</div>'
        "<script>(function(){"
        "var o=document.getElementById('click-block-overlay');"
        "var d=document.getElementById('overlay-dismiss');"
        "function remove(){if(o)o.remove();"
        "document.removeEventListener('keydown',onKey);}"
        "function onKey(e){if(e.key==='Escape')remove();}"
        "if(d)d.addEventListener('click',remove);"
        "o.addEventListener('click',function(e){if(e.target===o)remove();});"
        "document.addEventListener('keydown',onKey);"
        "})();</script>"
    )


@app.after_request
def inject_content_chaos(response):
    """Inject content-level disruptions (modal, cookie banner) into HTML
    responses just before the closing </body>. Non-HTML responses (static
    files, redirects, errors) are passed through untouched."""
    active = getattr(g, "chaos", set())
    if not active:
        return response
    # Skip redirects (3xx) — no HTML body to inject into.
    if 300 <= response.status_code < 400:
        return response
    ctype = response.headers.get("Content-Type", "")
    if "text/html" not in ctype:
        return response

    injections = ""
    if "popup_modal" in active:
        injections += _popup_modal_html()

    if "blocked_clicks" in active:
        injections += _blocked_clicks_html()

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

    template = "listing_drift.html" if getattr(g, "dom_drift", False) else "listing.html"
    return render_template(
        template,
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
    template = "detail_drift.html" if getattr(g, "dom_drift", False) else "detail.html"
    return render_template(template, item=item)


SHAPES = ["circle", "square", "triangle", "star", "diamond", "cross", "arrow", "heart"]


def _draw_shape(draw, shape, cx, cy, size, rng):
    half = size // 2
    if shape == "circle":
        draw.ellipse([cx - half, cy - half, cx + half, cy + half], outline=0, width=2)
    elif shape == "square":
        draw.rectangle([cx - half, cy - half, cx + half, cy + half], outline=0, width=2)
    elif shape == "triangle":
        draw.polygon([(cx, cy - half), (cx - half, cy + half), (cx + half, cy + half)], outline=0, width=2)
    elif shape == "star":
        pts = []
        for i in range(5):
            angle = i * 72 - 90
            outer_x = cx + int(half * cos(radians(angle)))
            outer_y = cy + int(half * sin(radians(angle)))
            pts.append((outer_x, outer_y))
            angle += 36
            inner_x = cx + int(half * 0.4 * cos(radians(angle)))
            inner_y = cy + int(half * 0.4 * sin(radians(angle)))
            pts.append((inner_x, inner_y))
        draw.polygon(pts, outline=0, width=2)
    elif shape == "diamond":
        draw.polygon([(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)], outline=0, width=2)
    elif shape == "cross":
        w = max(2, half // 2)
        draw.rectangle([cx - w, cy - half, cx + w, cy + half], outline=0, width=2)
        draw.rectangle([cx - half, cy - w, cx + half, cy + w], outline=0, width=2)
    elif shape == "arrow":
        draw.polygon([(cx - half, cy + half), (cx, cy - half), (cx + half, cy + half)], outline=0, width=2)
        draw.line([(cx, cy - half), (cx, cy)], fill=0, width=2)
    elif shape == "heart":
        r = half // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=2)
        draw.ellipse([cx - r + r // 2, cy - r, cx + r + r // 2, cy + r], outline=0, width=2)
        draw.polygon([(cx - r - 1, cy + r // 2), (cx + r + r // 2 + 1, cy + r // 2), (cx + r // 4, cy + half + 2)], outline=0, width=2)


def _render_tile(shape, seed):
    size = 70
    rng = random.Random(seed)
    img = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(0, 3)):
        draw.line(
            [(rng.randint(0, size), rng.randint(0, size)),
             (rng.randint(0, size), rng.randint(0, size))],
            fill=(rng.randint(200, 240),) * 3, width=1,
        )
    _draw_shape(draw, shape, size // 2, size // 2, 36, rng)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


_SHAPE_NAMES = {
    "circle": "a circle",
    "square": "a square",
    "triangle": "a triangle",
    "star": "a star",
    "diamond": "a diamond",
    "cross": "a cross",
    "arrow": "an arrow",
    "heart": "a heart",
}


def _build_captcha(cfg, target):
    """Deterministically build the tile grid for (seed, target).

    Returns (tiles, target_shape_key, correct_indices). Deterministic so the
    error-retry POST can re-render the exact same grid without storing the
    rendered images in the session cookie (which would blow past the browser's
    4KB per-cookie limit)."""
    rng = random.Random(cfg.get("seed", 0) * 1_000_003 + hash(target))
    tiled = [rng.choice(SHAPES) for _ in range(9)]
    target_shape = rng.choice(list(set(tiled)))
    correct_indices = [str(i) for i, s in enumerate(tiled) if s == target_shape]
    tiles = [_render_tile(s, rng.randint(0, 99999)) for s in tiled]
    return tiles, target_shape, correct_indices


@app.route("/captcha-gate", methods=["GET", "POST"])
def captcha_gate():
    cfg = load_chaos()
    target = request.args.get("target", "/")

    if request.method == "POST":
        target = request.form.get("target") or request.args.get("target", "/")
        expected = set(session.get("correct_indices", []))
        if not expected:
            return render_template("captcha_gate.html", target=target, error="Session expired, try again.", tiles=[], target_shape="?")
        submitted_raw = request.form.get("selected", "")
        submitted = set(submitted_raw.split(",")) if submitted_raw else set()
        if submitted == expected:
            parsed = urlparse(target)
            qs = parse_qs(parsed.query)
            qs["captcha_solved"] = ["1"]
            new_query = urlencode(qs, doseq=True)
            new_target = urlunparse(parsed._replace(query=new_query))
            session.pop("correct_indices", None)
            session.pop("target_shape", None)
            return redirect(new_target)
        # Re-render the identical grid from the seed rather than the session.
        tiles, _, _ = _build_captcha(cfg, target)
        return render_template(
            "captcha_gate.html",
            target=target,
            error="Incorrect selection, try again.",
            tiles=tiles,
            target_shape=_SHAPE_NAMES.get(session.get("target_shape", ""), "?"),
        )

    tiles, target_shape, correct_indices = _build_captcha(cfg, target)
    session["correct_indices"] = correct_indices
    session["target_shape"] = target_shape

    return render_template(
        "captcha_gate.html",
        tiles=tiles,
        target_shape=_SHAPE_NAMES[target_shape],
        target=target,
        error=None,
    )


@app.route("/interstitial")
def interstitial():
    """Serve a promo/interstitial page that interrupts navigation.

    The user must click through to return to the original target URL.
    The target URL is passed as a query parameter and appended with
    detour_handled=1 so the before_request hook doesn't intercept again.
    """
    target = request.args.get("target", "/")

    # Build the return URL with the detour_handled flag.
    parsed = urlparse(target)
    qs = parse_qs(parsed.query)
    qs["detour_handled"] = ["1"]
    new_query = urlencode(qs, doseq=True)
    return_target = urlunparse(parsed._replace(query=new_query))

    return render_template(
        "interstitial.html",
        target=target,
        return_url=return_target,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
