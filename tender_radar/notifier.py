import subprocess
import sys


class Notifier:
    """Shows a macOS notification after a check: when relevant new leads arrive or a portal fails.

    A check with nothing new stays silent, because checks run several times a day.
    """

    def run_finished(self, new_leads: list[dict], result: dict, error: str = ""):
        failed = [name for name, item in result.get("sources", {}).items() if not item["ok"]]
        if error:
            self.show("Check failed", error[:150])
        elif new_leads:
            self.show(f"{len(new_leads)} new tender lead{'s' if len(new_leads) != 1 else ''}", _top_titles(new_leads))
        if failed and not error:
            self.show("Some portals failed", f"{', '.join(failed)}. See the dashboard for details.")

    def show(self, title: str, message: str):
        if sys.platform != "darwin":
            return
        script = f"display notification {_quote(message)} with title \"Tender Radar\" subtitle {_quote(title)}"
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def _top_titles(leads: list[dict]) -> str:
    best = sorted(leads, key=lambda lead: -lead["score"])[:2]
    return " · ".join((lead.get("title_en") or lead["title"])[:70] for lead in best)


def _quote(text: str) -> str:
    """AppleScript string literal: tender titles can hold quotes and backslashes."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
