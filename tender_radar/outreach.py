"""Introduction emails to buyers and partners: contacts, drafts the team approves, and sending.

Claude drafts each email from the company profile and, when given, the tender that links the company to
the contact. Nothing is sent on its own: a person reads the draft, edits it if needed, and clicks Send.
Two ways to send. Through the SMTP account in config.json -> alerts -> email, with the documents the company
profile marks "attach"; `outreach.daily_limit` caps how many go out a day, so a mistake cannot become a flood.
Or in Outlook on the web: the dashboard opens a filled-in compose window, the user drags the PDF in and sends
it from their own mailbox, then marks the email as sent here.
"""

import json
import mimetypes
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

CONTACT_ROLES = ("buyer", "partner", "other")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_DAILY_LIMIT = 20
OUTLOOK_WEB_COMPOSE = "https://outlook.office.com/mail/deeplink/compose"
SENT_VIA = ("smtp", "outlook-web")
MAX_ATTACHMENTS_BYTES = 15 * 1024 * 1024  # most mail servers refuse messages over 20-25 MB once encoded

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        person TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'other',
        cr TEXT NOT NULL DEFAULT '',
        lead_key TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS intros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER NOT NULL,
        lead_key TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        error TEXT NOT NULL DEFAULT '',
        attachments TEXT NOT NULL DEFAULT '[]',
        created TEXT NOT NULL,
        sent TEXT NOT NULL DEFAULT '',
        via TEXT NOT NULL DEFAULT ''
    )""",
)
CONTACT_FIELDS = ("company", "person", "email", "role", "cr", "lead_key", "notes")


class OutreachStore:
    """Contacts and their introduction emails, in the lead database."""

    def __init__(self, db):
        self.db = db
        for statement in SCHEMA:
            self.db.execute(statement)
        if "via" not in {row[1] for row in self.db.execute("PRAGMA table_info(intros)")}:
            self.db.execute("ALTER TABLE intros ADD COLUMN via TEXT NOT NULL DEFAULT ''")
        self.db.commit()

    def contacts(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT c.*, (SELECT MAX(sent) FROM intros WHERE contact_id = c.id AND status = 'sent') AS last_sent
               FROM contacts c ORDER BY c.created DESC, c.id DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def contact(self, contact_id: int) -> dict:
        row = self.db.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        if not row:
            raise ValueError(f"No contact {contact_id}")
        return dict(row)

    def save_contact(self, fields: dict) -> int:
        """Adds a contact, or updates it when `fields` has an id. Returns the id."""
        values = {name: str(fields.get(name) or "").strip() for name in CONTACT_FIELDS}
        if not values["company"]:
            raise ValueError("Give the company name")
        if not EMAIL.match(values["email"]):
            raise ValueError(f"Not an email address: {values['email'] or '(empty)'}")
        if values["role"] not in CONTACT_ROLES:
            values["role"] = "other"
        if fields.get("id"):
            assignments = ", ".join(f"{name} = ?" for name in values)
            self.contact(int(fields["id"]))
            self.db.execute(f"UPDATE contacts SET {assignments} WHERE id = ?", [*values.values(), int(fields["id"])])
            self.db.commit()
            return int(fields["id"])
        cursor = self.db.execute(
            f"INSERT INTO contacts ({', '.join(values)}, created) VALUES ({', '.join('?' * len(values))}, ?)",
            [*values.values(), _now()],
        )
        self.db.commit()
        return cursor.lastrowid

    def delete_contact(self, contact_id: int):
        """Removes the contact and its drafts. Sent emails stay, as a record of what went out."""
        self.db.execute("DELETE FROM intros WHERE contact_id = ? AND status != 'sent'", (contact_id,))
        self.db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        self.db.commit()

    def intros(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT i.*, COALESCE(c.company, '(deleted contact)') AS company, COALESCE(c.person, '') AS person,
                      COALESCE(c.email, '') AS email
               FROM intros i LEFT JOIN contacts c ON c.id = i.contact_id
               ORDER BY CASE i.status WHEN 'sent' THEN 1 ELSE 0 END, i.created DESC, i.id DESC"""
        ).fetchall()
        return [dict(row) | {"attachments": json.loads(row["attachments"])} for row in rows]

    def intro(self, intro_id: int) -> dict:
        row = self.db.execute("SELECT * FROM intros WHERE id = ?", (intro_id,)).fetchone()
        if not row:
            raise ValueError(f"No email {intro_id}")
        return dict(row)

    def add_draft(self, contact_id: int, lead_key: str, subject: str, body: str) -> int:
        cursor = self.db.execute(
            "INSERT INTO intros (contact_id, lead_key, subject, body, created) VALUES (?, ?, ?, ?, ?)",
            (contact_id, lead_key, subject, body, _now()),
        )
        self.db.commit()
        return cursor.lastrowid

    def update_draft(self, intro_id: int, subject: str, body: str):
        if self.intro(intro_id)["status"] == "sent":
            raise ValueError("This email was sent already")
        if not subject.strip() or not body.strip():
            raise ValueError("The email needs a subject and a message")
        self.db.execute(
            "UPDATE intros SET subject = ?, body = ? WHERE id = ?", (subject.strip(), body.strip(), intro_id)
        )
        self.db.commit()

    def delete_draft(self, intro_id: int):
        if self.intro(intro_id)["status"] == "sent":
            raise ValueError("A sent email stays in the record")
        self.db.execute("DELETE FROM intros WHERE id = ?", (intro_id,))
        self.db.commit()

    def mark_sent(self, intro_id: int, attachments: list[str], via: str = "smtp"):
        """Records the email as sent. `via` is "smtp" (sent here) or "outlook-web" (sent by the user in Outlook)."""
        if via not in SENT_VIA:
            raise ValueError(f"Unknown way of sending: {via}")
        if self.intro(intro_id)["status"] == "sent":
            raise ValueError("This email was sent already")
        self.db.execute(
            "UPDATE intros SET status = 'sent', error = '', sent = ?, attachments = ?, via = ? WHERE id = ?",
            (_now(), json.dumps(attachments, ensure_ascii=False), via, intro_id),
        )
        self.db.commit()

    def mark_failed(self, intro_id: int, error: str):
        self.db.execute("UPDATE intros SET status = 'failed', error = ? WHERE id = ?", (error[:300], intro_id))
        self.db.commit()

    def sent_today(self) -> int:
        today = _now()[:10]
        query = "SELECT COUNT(*) FROM intros WHERE status = 'sent' AND sent >= ?"
        return self.db.execute(query, (today,)).fetchone()[0]


class Mailer:
    """Sends one introduction email through the SMTP account set up for alerts."""

    def __init__(self, config: dict):
        self.smtp = config.get("alerts", {}).get("email", {})
        self.settings = config.get("outreach", {})
        self.password = os.environ.get(self.smtp.get("password_env", "TENDER_RADAR_SMTP_PASSWORD"), "")

    @property
    def sender(self) -> str:
        return self.smtp.get("from") or self.smtp.get("username", "")

    @property
    def ready(self) -> bool:
        return bool(self.smtp.get("smtp_host") and self.sender)

    @property
    def daily_limit(self) -> int:
        return int(self.settings.get("daily_limit", DEFAULT_DAILY_LIMIT))

    def build(self, intro: dict, contact: dict, profile: dict, attachments: list[tuple[str, bytes]]) -> EmailMessage:
        details = profile["details"]
        message = EmailMessage()
        message["Subject"] = intro["subject"]
        message["From"] = formataddr((details.get("name") or details.get("legal_name") or "", self.sender))
        message["To"] = formataddr((contact.get("person") or "", contact["email"]))
        if details.get("email") and details["email"] != self.sender:
            message["Reply-To"] = details["email"]
        if self.settings.get("bcc"):
            message["Bcc"] = ", ".join(self.settings["bcc"])
        signature = details.get("signature", "").strip()
        message.set_content(intro["body"].strip() + (f"\n\n{signature}" if signature else "") + "\n")
        if sum(len(data) for _, data in attachments) > MAX_ATTACHMENTS_BYTES:
            raise ValueError("The attached documents are over 15 MB. Untick Attach on the large ones in Company.")
        for name, data in attachments:
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            maintype, subtype = kind.split("/", 1)
            message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        return message

    def send(self, message: EmailMessage):
        if not self.ready:
            raise ValueError("Set up the email account first: config.json -> alerts -> email (smtp_host, username)")
        port = int(self.smtp.get("smtp_port", 587))
        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(self.smtp["smtp_host"], port, timeout=60) as smtp:
            if port != 465:
                smtp.starttls()
            if self.smtp.get("username"):
                smtp.login(self.smtp["username"], self.password)
            smtp.send_message(message)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
