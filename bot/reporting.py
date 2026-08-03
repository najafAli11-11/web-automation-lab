"""Structured logging, screenshots, and run summary (PLANNING §4 Reporting).

Every event is appended to ``events.jsonl`` with a UTC timestamp; unexpected
states get a screenshot under the run dir; ``summary()`` writes and prints the
end-of-run verdict (items extracted, disruptions and how each was resolved,
total retries, data completeness). The reporter only records what the bot itself
observed — it never reads site internals (chaos.json/items.json).
"""

import json
from datetime import datetime, timezone
from pathlib import Path


# Fields every extracted item must carry to count as complete (PLANNING §1
# data model). ``title`` is validated separately so a bad id still reports.
REQUIRED_FIELDS = ("id", "title", "platform", "price", "year",
                   "condition", "region", "description")


def _now():
    return datetime.now(timezone.utc).isoformat()


class Reporter:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self._events_fh = open(self.events_path, "a", encoding="utf-8")
        self.seed = None
        self.events = []
        self.items = []
        self.screenshots = []
        self._shot_count = 0

    def set_seed(self, seed):
        """Record the run seed so a gauntlet failure is reproducible."""
        self.seed = seed
        self.log_event("run_start", detail={"seed": seed})

    def log_event(self, action, scenario=None, strategy=None, outcome=None,
                  retry=None, detail=None):
        """Append one structured event to the JSONL log and in-memory list.

        Optional fields are omitted when None so the log stays readable."""
        event = {"ts": _now(), "action": action}
        if scenario is not None:
            event["scenario"] = scenario
        if strategy is not None:
            event["strategy"] = strategy
        if outcome is not None:
            event["outcome"] = outcome
        if retry is not None:
            event["retry"] = retry
        if detail is not None:
            event["detail"] = detail
        self.events.append(event)
        self._events_fh.write(json.dumps(event) + "\n")
        self._events_fh.flush()
        return event

    def log_item_extracted(self, item):
        """Record a fully extracted item (a dict of its fields)."""
        record = dict(item)
        self.items.append(record)
        self.log_event(
            "item_extracted", outcome="ok",
            detail={"id": record.get("id"), "title": record.get("title")},
        )
        return record

    def screenshot(self, page, name):
        """Capture the page to ``runs/`` for an unexpected/escalated state.

        Never raises — a screenshot failure is itself logged, not fatal."""
        self._shot_count += 1
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))
        filename = f"{self._shot_count:03d}_{safe}.png"
        filepath = self.run_dir / filename
        try:
            page.screenshot(path=str(filepath))
        except Exception as e:  # screenshotting must not abort the crawl
            self.log_event("screenshot_failed",
                           detail={"name": name, "error": str(e)})
            return None
        self.screenshots.append(str(filepath))
        self.log_event("screenshot", detail={"name": name, "path": str(filepath)})
        return str(filepath)

    def _disruptions(self):
        """Group scenario events into {scenario: {outcome: count}}."""
        by_scenario = {}
        for e in self.events:
            scenario = e.get("scenario")
            if not scenario:
                continue
            outcome = e.get("outcome") or "seen"
            by_scenario.setdefault(scenario, {})
            by_scenario[scenario][outcome] = by_scenario[scenario].get(outcome, 0) + 1
        return by_scenario

    def summary(self, expected=None):
        """Build, persist (summary.json), and print the run verdict."""
        total_retries = sum(1 for e in self.events if e.get("retry") is not None)
        disruptions = self._disruptions()

        seen_ids = set()
        duplicate_ids = []
        incomplete = []
        for item in self.items:
            item_id = item.get("id")
            if item_id in seen_ids:
                duplicate_ids.append(item_id)
            seen_ids.add(item_id)
            gaps = [f for f in REQUIRED_FIELDS if not str(item.get(f, "")).strip()]
            if gaps:
                incomplete.append({"id": item_id, "missing": gaps})

        complete = bool(self.items) and not incomplete and not duplicate_ids
        if expected is not None:
            complete = complete and len(seen_ids) == expected
        verdict = "PASS" if complete else "FAIL"

        report = {
            "seed": self.seed,
            "items_extracted": len(self.items),
            "unique_items": len(seen_ids),
            "items_expected": expected,
            "total_retries": total_retries,
            "disruptions": disruptions,
            "duplicate_ids": duplicate_ids,
            "incomplete_items": incomplete,
            "screenshots": len(self.screenshots),
            "verdict": verdict,
        }

        with open(self.run_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        self._print(report)
        return report

    def _print(self, report):
        print("\n===== RUN SUMMARY =====")
        print(f"seed:              {report['seed']}")
        expected = report["items_expected"]
        exp = "?" if expected is None else expected
        print(f"items extracted:   {report['items_extracted']} "
              f"({report['unique_items']} unique / {exp} expected)")
        print(f"total retries:     {report['total_retries']}")
        if report["disruptions"]:
            print("disruptions handled:")
            for scenario, outcomes in report["disruptions"].items():
                detail = ", ".join(f"{k}={v}" for k, v in outcomes.items())
                print(f"  - {scenario}: {detail}")
        else:
            print("disruptions handled: none")
        if report["duplicate_ids"]:
            print(f"duplicate ids:     {report['duplicate_ids']}")
        if report["incomplete_items"]:
            print(f"incomplete items:  {report['incomplete_items']}")
        print(f"screenshots:       {report['screenshots']}")
        print(f"VERDICT:           {report['verdict']}")
        print("=======================\n")

    def close(self):
        if self._events_fh and not self._events_fh.closed:
            self._events_fh.close()
