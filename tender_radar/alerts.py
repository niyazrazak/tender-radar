"""Sends lead digests, deadline reminders and failure alerts to email and Telegram.

The macOS notification (`Notifier`) only reaches someone sitting at this Mac. These channels
reach the team anywhere. Each channel is off until it is set up in `config.json` -> "alerts";
secrets (SMTP password, bot token) come from environment variables, never from config.json.
"""

import html
import os
import smtplib
from email.message import EmailMessage

import requests

from tender_radar.notifier import Notifier
from tender_radar.small_company import DEFAULT_MAX_UPFRONT_USD, assess

DIGEST_LIMIT = 15
TELEGRAM_LIMIT = 4000  # Telegram rejects messages over 4096 characters


class EmailChannel:
    def __init__(self, settings: dict):
        self.settings = settings
        self.password = os.environ.get(settings.get("password_env", "TENDER_RADAR_SMTP_PASSWORD"), "")

    @property
    def ready(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("smtp_host") and self.settings.get("to"))

    def send(self, subject: str, text: str, html_body: str):
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.get("from") or self.settings.get("username", "")
        message["To"] = ", ".join(self.settings["to"])
        message.set_content(text)
        message.add_alternative(html_body, subtype="html")
        port = int(self.settings.get("smtp_port", 587))
        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(self.settings["smtp_host"], port, timeout=30) as smtp:
            if port != 465:
                smtp.starttls()
            if self.settings.get("username"):
                smtp.login(self.settings["username"], self.password)
            smtp.send_message(message)


class TelegramChannel:
    def __init__(self, settings: dict):
        self.settings = settings
        self.token = os.environ.get(settings.get("token_env", "TENDER_RADAR_TELEGRAM_TOKEN"), "")

    @property
    def ready(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("chat_id") and self.token)

    def send(self, subject: str, text: str, html_body: str):
        body = f"<b>{html.escape(subject)}</b>\n\n{_telegram_html(text)}"
        response = requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={
                "chat_id": self.settings["chat_id"], "text": body[:TELEGRAM_LIMIT],
                "parse_mode": "HTML", "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()


class Alerts:
    """Decides what is worth a message after a check, and sends it on every channel that is set up."""

    def __init__(self, config: dict, notifier: Notifier | None = None):
        settings = config.get("alerts", {})
        self.settings = settings
        self.notifier = notifier or Notifier()
        self.channels = [
            channel for channel in (
                EmailChannel(settings.get("email", {})), TelegramChannel(settings.get("telegram", {}))
            ) if channel.ready
        ]
        self.min_fit = settings.get("digest_min_fit")
        small = config.get("small_company", {})
        self.small_company = bool(small.get("enabled"))
        self.max_upfront = small.get("max_upfront_usd", DEFAULT_MAX_UPFRONT_USD)
        self.dashboard = settings.get("dashboard_url", "")

    def run_finished(self, new_leads: list[dict], result: dict, error: str = ""):
        self.notifier.run_finished(new_leads, result, error)
        failed = {name: item["error"] for name, item in result.get("sources", {}).items() if not item["ok"]}
        if error:
            self._send("Tender Radar check failed", error)
        elif failed:
            lines = [f"- {name}: {reason}" for name, reason in failed.items()]
            self._send("Tender Radar: some portals failed", "\n".join(lines))
        leads = self.digest_leads(new_leads)
        if leads:
            count = len(leads)
            self._send(f"{count} new tender lead{'s' if count != 1 else ''}", *self._digest(leads))

    def send_reminders(self, store) -> int:
        """One message for every shortlisted or bidding lead whose deadline is near. Returns the count."""
        due = store.due_reminders(self.settings.get("reminder_days", [7, 3, 1]))
        if not due:
            return 0
        leads = [lead | {"deadline": deadline, "days_left": days} for lead, deadline, days in due]
        subject = f"Deadline reminder: {len(leads)} tender{'s' if len(leads) != 1 else ''}"
        text, html_body = self._digest(leads, reminder=True)
        self.notifier.show(subject, "; ".join(_title(lead)[:60] for lead in leads[:2]))
        if self._send(subject, text, html_body):
            for lead, deadline, days in due:
                store.mark_reminded(lead["key"], deadline, days)
        return len(leads)

    def test(self) -> list[str]:
        """Sends a test message on each channel. Returns one line per channel."""
        if not self.channels:
            return ["No alert channel is set up. See config.json -> alerts."]
        lines = []
        for channel in self.channels:
            try:
                text = "Alerts work. New leads and deadline reminders come here."
                channel.send("Tender Radar test", text, f"<p>{text}</p>")
                lines.append(f"{type(channel).__name__}: sent")
            except Exception as error:
                lines.append(f"{type(channel).__name__}: FAILED: {error}")
        return lines

    def digest_leads(self, leads: list[dict]) -> list[dict]:
        """With AI on, only leads it rated a fit (or did not rate yet) go into the digest.
        In small company mode, only leads a small company can afford to bid on."""
        if self.min_fit is not None:
            leads = [lead for lead in leads if lead.get("ai_fit") is None or lead["ai_fit"] >= self.min_fit]
        if self.small_company:
            leads = [lead for lead in leads if assess(lead, self.max_upfront)["fits"]]
        return leads

    def _digest(self, leads: list[dict], reminder: bool = False) -> tuple[str, str]:
        ordered = sorted(leads, key=lambda lead: (-(lead.get("ai_fit") or 0), -lead["score"]))[:DIGEST_LIMIT]
        text_items, html_items = [], []
        for lead in ordered:
            facts = _facts(lead, reminder)
            reason = lead.get("ai_reason") or ""
            lines = [f"• {_title(lead)}", f"  {facts}", f"  {reason}" if reason else "", f"  {lead['url']}"]
            text_items.append("\n".join(line for line in lines if line))
            html_items.append(
                f'<li><a href="{html.escape(lead["url"])}">{html.escape(_title(lead))}</a><br>'
                f'<small>{html.escape(facts)}</small>{f"<br><i>{html.escape(reason)}</i>" if reason else ""}</li>'
            )
        more = len(leads) - len(ordered)
        footer = [f"…and {more} more." if more > 0 else "", f"Dashboard: {self.dashboard}" if self.dashboard else ""]
        text = "\n\n".join(text_items + [line for line in footer if line])
        footer_html = "".join(f"<p>{html.escape(line)}</p>" for line in footer if line)
        html_body = f"<ul>{''.join(html_items)}</ul>{footer_html}"
        return text, html_body

    def _send(self, subject: str, text: str, html_body: str = "") -> bool:
        """True if at least one channel took the message."""
        sent = False
        for channel in self.channels:
            try:
                channel.send(subject, text, html_body or f"<pre>{html.escape(text)}</pre>")
                sent = True
            except Exception as error:  # one channel down must not stop the other
                print(f"  ! {type(channel).__name__} failed: {error}", flush=True)
        return sent


def _title(lead: dict) -> str:
    return lead.get("title_en") or lead["title"]


def _facts(lead: dict, reminder: bool) -> str:
    buyer = lead.get("buyer_en") or lead.get("buyer") or ""
    parts = [buyer, lead.get("country", "")]
    if reminder:
        left = lead["days_left"]
        when = "today" if left == 0 else f"in {left} day{'s' if left != 1 else ''}"
        kind = "your bid deadline" if lead.get("bid_due") else "closes"
        parts.append(f"{kind} {when} ({lead['deadline']})")
        parts.append(lead["lead_status"])
    elif lead.get("closing"):
        parts.append(f"closes {lead['closing']}")
    if lead.get("ai_fit") is not None:
        parts.append(f"fit {lead['ai_fit']}/10")
    return " · ".join(part for part in parts if part)


def _telegram_html(text: str) -> str:
    return html.escape(text)
