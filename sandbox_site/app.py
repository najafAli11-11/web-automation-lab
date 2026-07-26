"""Flask sandbox server for the Resilient Web Automation Lab.

Serves a paginated listing page and per-item detail pages, rendering
retro-game data from data/items.json. Chaos middleware is added in a
later step; this module is the plain, working baseline.
"""

import json
import math
from pathlib import Path

from flask import Flask, abort, render_template, request

app = Flask(__name__)

# Data lives next to this file, in data/items.json.
DATA_PATH = Path(__file__).resolve().parent / "data" / "items.json"
PER_PAGE = 8


def load_items():
    """Read and return the list of items from items.json.

    Read on each request so edits to the dataset show up without a
    restart. The file is small, so the cost is negligible.
    """
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


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
