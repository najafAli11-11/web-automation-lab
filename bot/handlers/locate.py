from playwright.sync_api import TimeoutError as PlaywrightTimeout


class LocateError(Exception):
    pass


_STATE_MAP = {
    "visible": "visible",
    "attached": "attached",
    "clickable": "visible",
}


def first(context, selectors, timeout=5, state="visible"):
    pw_state = _STATE_MAP.get(state, "visible")
    ms = int(timeout * 1000)
    # Two-phase probe. Selector chains are usually fallbacks where only one
    # variant is present (e.g. the normal vs dom_drift templates expose
    # a.item-link OR a.prod-title, never both). A quick pass finds the present
    # variant instantly instead of burning the full timeout on the absent
    # first selector; only if nothing is present yet do we pay the full
    # timeout on a second pass, which covers a genuinely still-rendering
    # element. No fixed sleeps — every wait is a bounded wait_for.
    for probe_ms in (250, ms):
        for sel in selectors:
            loc = context.locator(sel).first
            try:
                loc.wait_for(state=pw_state, timeout=probe_ms)
                return loc
            except PlaywrightTimeout:
                continue
    raise LocateError(f"none of [{', '.join(selectors)}] matched")


def all_matches(context, selectors, timeout=5):
    ms = int(timeout * 1000)
    for sel in selectors:
        loc = context.locator(sel)
        try:
            loc.first.wait_for(state="attached", timeout=ms)
            return loc.all()
        except PlaywrightTimeout:
            continue
    raise LocateError(f"none of [{', '.join(selectors)}] matched")


def is_present(context, selectors, timeout=2):
    try:
        first(context, selectors, timeout=timeout)
        return True
    except LocateError:
        return False
