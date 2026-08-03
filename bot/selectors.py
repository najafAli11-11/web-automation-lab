PAGE_IDENTITY = {
    "listing": ["ul#listing", "ol.game-list"],
    "detail": ["dl#item-detail", "table.detail-grid"],
    "captcha": ["form#captcha-form"],
    "interstitial": ["a#continue-link"],
}

PAGE_TITLE = {
    "listing": "h1",
    "detail_normal": "h1#item-title",
    "detail_drift": "h2.detail-heading",
}

LISTING_ITEMS_CONTAINER = ["ul#listing", "ol.game-list"]

LISTING_ITEM = ["li.item", "li.product-card"]

ITEM_LINK = ["a.item-link", "a.prod-title"]

ITEM_PLATFORM = ["span.platform", "span.prod-platform"]

ITEM_PRICE = ["span.price", "span.prod-price"]

ITEM_CONDITION = ["span.condition", "span.prod-condition"]

LISTING_SUMMARY = ["p", "p.listing-summary"]

PAGINATION_CONTAINER = ["nav#pagination", "nav#pag-nav"]

PAGINATION_NEXT = [
    "a[rel='next']",
    "a.next",
    "a.next-link",
    "a:has-text('Next')",
]

PAGINATION_PREV = [
    "a[rel='prev']",
    "a.prev",
    "a.prev-link",
    "a:has-text('Previous')",
]

DETAIL_BACK_LINK = ["a.back-link"]

DETAIL_TITLE = ["h1#item-title", "h2.detail-heading"]

DETAIL_FIELDS = {
    "id": ["dd.field-id", "td.val-id"],
    "platform": ["dd.field-platform", "td.val-platform"],
    "price": ["dd.field-price", "td.val-price"],
    "year": ["dd.field-year", "td.val-year"],
    "condition": ["dd.field-condition", "td.val-condition"],
    "region": ["dd.field-region", "td.val-region"],
    "description": ["dd.field-description", "td.val-description"],
}

CAPTCHA_FORM = ["#captcha-form"]

CAPTCHA_TILES = [".captcha-grid .tile"]

CAPTCHA_SUBMIT = ["button[type='submit']"]

CAPTCHA_ERROR = [".error"]

INTERSTITIAL_CONTINUE = ["#continue-link", "a.continue-link"]

POPUP_OVERLAY = ["#popup-overlay"]

POPUP_CLOSE = ["#popup-close", "button.modal-close"]

COOKIE_BANNER = ["#cookie-banner"]

COOKIE_ACCEPT = ["#accept-cookies"]

BLOCK_OVERLAY = ["#click-block-overlay"]

BLOCK_DISMISS = ["#overlay-dismiss"]
