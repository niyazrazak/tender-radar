"use strict";

/* Outreach: introduction emails to buyers and partners. Claude drafts, a person reads and sends.
   Two ways to send. "Open in Outlook web" fills a compose window in the user's own mailbox and shows the
   PDF in Finder to drag in; the user sends there and clicks "Mark as sent". "Send…" goes out through SMTP
   when it is set up, and asks for a second click that names the recipient. */

const CONTACT_ROLES = { buyer: "Buyer", partner: "Partner", other: "Other" };

const outreach = {
  data: null,
  busy: "",          // what is running: "contact", "draft:<id>", "send:<id>", …
  confirming: null,  // id of the draft whose Send waits for the second click
  prefill: null,     // contact form values passed in from a lead

  isOpen() {
    return !$("outreachPanel").hidden;
  },

  async toggle() {
    if (this.isOpen()) return this.close();
    await this.open();
  },

  /** Opens the panel; `prefill` fills the new-contact form (company, role, CR, lead) from a lead. */
  async open(prefill = null) {
    this.prefill = prefill;
    $("outreachPanel").hidden = false;
    $("outreachBody").innerHTML = '<div class="note">Loading…</div>';
    try {
      this.data = await api.get("/api/outreach");
      this.render();
      if (prefill) $("outreachBody").querySelector("[name=email]")?.focus();
    } catch (error) {
      $("outreachBody").innerHTML = `<div class="note">Could not load: ${esc(error.message)}</div>`;
    }
  },

  close() {
    $("outreachPanel").hidden = true;
    this.confirming = null;
  },

  render() {
    const { intros, contacts, mailer, attachments, ai_enabled: aiEnabled } = this.data;
    const drafts = intros.filter((i) => i.status !== "sent");
    const sent = intros.filter((i) => i.status === "sent");
    $("outreachBody").innerHTML = `
      <div class="drawer-head"><span>Outreach · introduction emails</span>
        <button class="icon-btn" data-close-outreach aria-label="Close">
          <svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button></div>
      ${mailerNote(mailer, attachments)}
      <h3>Drafts to review <span class="cap">${drafts.length || ""}</span></h3>
      ${drafts.length ? drafts.map((intro) => draftCard(intro, this)).join("")
        : '<p class="cap">No drafts. Add a contact below, or use <b>Introduce us</b> in a tender\'s panel.</p>'}
      <h3>Contacts</h3>
      ${contactForm(this.prefill, aiEnabled, this.busy)}
      ${contacts.length ? contactsTable(contacts, aiEnabled, this.busy) : ""}
      ${sent.length ? `<h3>Sent</h3>${sentTable(sent)}` : ""}`;
  },

  bind() {
    const panel = $("outreachPanel");
    panel.addEventListener("click", (e) => {
      if (e.target === panel || e.target.closest("[data-close-outreach]")) return this.close();
      const button = e.target.closest("[data-act]");
      if (!button) return;
      const id = Number(button.dataset.id);
      const actions = {
        draft: () => this.post(`draft:${id}`, "/api/intro-draft", { contact_id: id }, "Draft ready. Read it, then send."),
        "remove-contact": () => this.post("", "/api/contact-delete", { id }),
        save: () => this.post("", "/api/intro-update", this.draftValues(id), "Saved"),
        delete: () => this.post("", "/api/intro-delete", { id }),
        send: () => { this.confirming = id; this.render(); },
        outlook: () => this.openOutlook(id),
        "show-pdf": () => this.showPdf(),
        "mark-sent": () => this.post("", "/api/intro-mark-sent", { id }, "Marked as sent"),
        cancel: () => { this.confirming = null; this.render(); },
        confirm: () => this.send(id),
      };
      actions[button.dataset.act]?.();
    });
    panel.addEventListener("submit", (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const contact = Object.fromEntries(form.entries());
      contact.draft = form.has("draft");
      this.prefill = null;
      this.post("contact", "/api/contact", contact, contact.draft ? "Contact added and email drafted" : "Contact added");
    });
  },

  draftValues(id) {
    const card = $("outreachBody").querySelector(`[data-draft="${id}"]`);
    return { id, subject: card.querySelector("[name=subject]").value, body: card.querySelector("[name=body]").value };
  },

  /** Opens Outlook on the web with the email filled in, saves the edits, and shows the PDF to drag in.
      The window opens first, inside the click, so the browser does not block it as a pop-up. */
  async openOutlook(id) {
    const values = this.draftValues(id);
    const intro = this.data.intros.find((item) => item.id === id);
    const signature = (this.data.signature || "").trim();
    const params = new URLSearchParams({
      to: intro.email, subject: values.subject, body: `${values.body.trim()}${signature ? `\n\n${signature}` : ""}\n`,
    });
    window.open(`${this.data.outlook_web}?${params.toString().replace(/\+/g, "%20")}`, "_blank", "noopener");
    await this.post("", "/api/intro-update", values);
    if (this.data.attachments.length && this.data.can_reveal) await this.showPdf();
  },

  async showPdf() {
    const result = await api.post("/api/company-reveal", {});
    toast(result.ok ? "Drag the PDF from Finder into the Outlook email, send it, then click Mark as sent"
      : `Could not show the PDF: ${result.data.error}`);
  },

  /** Saves the edits first, so what was on screen is what goes out. */
  async send(id) {
    this.confirming = null;
    const values = this.draftValues(id);
    const saved = await this.post(`send:${id}`, "/api/intro-update", values);
    if (saved) await this.post(`send:${id}`, "/api/intro-send", { id }, "Email sent");
  },

  async post(busy, path, body, done = "") {
    this.busy = busy;
    if (busy) this.render();
    try {
      const result = await api.post(path, body);
      if (!result.ok) throw new Error(result.data.error);
      this.data = result.data;
      if (done) toast(done);
      return true;
    } catch (error) {
      toast(error.message);
      // A step may have half worked (contact saved but no draft, send failed): show what is stored now.
      this.data = await api.get("/api/outreach").catch(() => this.data);
      return false;
    } finally {
      this.busy = "";
      this.render();
    }
  },
};

function mailerNote(mailer, attachments) {
  const files = attachments.length
    ? `The document to attach: ${attachments.map(esc).join(", ")}.`
    : "No document is marked <b>Attach</b> in Company, so there is no PDF to attach.";
  const smtp = mailer.ready
    ? ` Or <b>Send…</b> sends it from ${esc(mailer.sender)} with the PDF attached (${mailer.sent_today} of ${mailer.daily_limit} sent today).`
    : "";
  return `<p class="cap"><b>Open in Outlook web</b> opens the email in your own mailbox and shows the PDF in Finder:
    drag it in, click Send in Outlook, then <b>Mark as sent</b> here.${smtp} ${files}</p>`;
}

function draftCard(intro, state) {
  const busy = state.busy === `send:${intro.id}`;
  const confirming = state.confirming === intro.id;
  const to = `${intro.person ? `${esc(intro.person)}, ` : ""}${esc(intro.company)} &lt;${esc(intro.email)}&gt;`;
  const controls = confirming
    ? `<button class="btn primary" data-act="confirm" data-id="${intro.id}">Send to ${esc(intro.email)}</button>
       <button class="btn ghost" data-act="cancel" data-id="${intro.id}">Cancel</button>`
    : `<button class="btn primary" data-act="outlook" data-id="${intro.id}" ${state.busy ? "disabled" : ""}
         title="Opens a new email in Outlook on the web with this text">Open in Outlook web</button>
       ${state.data.can_reveal && state.data.attachments.length ? `<button class="btn ghost" data-act="show-pdf" data-id="${intro.id}">Show PDF</button>` : ""}
       <button class="btn ghost" data-act="mark-sent" data-id="${intro.id}" ${state.busy ? "disabled" : ""}
         title="You sent it in Outlook: record it here">Mark as sent</button>
       ${state.data.mailer.ready ? `<button class="btn ghost" data-act="send" data-id="${intro.id}" ${state.busy ? "disabled" : ""}>Send…</button>` : ""}
       <button class="btn ghost" data-act="save" data-id="${intro.id}" ${state.busy ? "disabled" : ""}>Save edits</button>
       <button class="btn ghost" data-act="draft" data-id="${intro.contact_id}" ${state.busy ? "disabled" : ""}
         title="Claude writes a new draft; this one stays">Draft again</button>
       <button class="link" data-act="delete" data-id="${intro.id}">Delete</button>`;
  return `<div class="intro" data-draft="${intro.id}">
      <div class="cap">To ${to}${intro.lead_key ? " · about a tender" : ""}</div>
      ${intro.status === "failed" ? `<div class="fail">Not sent: ${esc(intro.error)}</div>` : ""}
      <input name="subject" value="${esc(intro.subject)}" aria-label="Subject">
      <textarea name="body" rows="10" aria-label="Message">${esc(intro.body)}</textarea>
      <div class="cap">Your signature from Company is added below the message.</div>
      <div class="analyze-controls">${controls}${busy ? '<span class="busy">Sending…</span>' : ""}</div>
    </div>`;
}

function contactForm(prefill, aiEnabled, busy) {
  const p = prefill || {};
  const roles = Object.entries(CONTACT_ROLES).map(([value, label]) =>
    `<option value="${value}" ${(p.role || "buyer") === value ? "selected" : ""}>${label}</option>`).join("");
  return `<form class="contact-form ${prefill ? "prefilled" : ""}">
      ${prefill ? `<p class="cap">From the tender: add the email address of the person to write to.</p>` : ""}
      <div class="profile-grid">
        <label>Company<input name="company" required value="${esc(p.company)}"></label>
        <label>Contact person<input name="person" value="${esc(p.person)}"></label>
        <label>Email<input name="email" type="email" required value="${esc(p.email)}"></label>
        <label>Type<select name="role">${roles}</select></label>
        <label>CR number<input name="cr" value="${esc(p.cr)}"></label>
        <label>Notes for the email<input name="notes" value="${esc(p.notes)}" placeholder="How you know them, what to offer"></label>
      </div>
      <input type="hidden" name="lead_key" value="${esc(p.lead_key)}">
      <div class="analyze-controls">
        <button class="btn ${prefill ? "primary" : "ghost"}" type="submit" ${busy ? "disabled" : ""}>Add contact</button>
        <label class="check"><input type="checkbox" name="draft" ${aiEnabled ? "checked" : "disabled"}> Draft an email now</label>
        ${busy === "contact" ? '<span class="busy">Claude is writing…</span>' : ""}
      </div></form>`;
}

function contactsTable(contacts, aiEnabled, busy) {
  const rows = contacts.map((c) => `<tr>
      <td dir="auto">${esc(c.company)}${c.cr ? ` <span class="cap">CR ${esc(c.cr)}</span>` : ""}
        <div class="cap">${esc(c.person)}${c.person ? " · " : ""}${esc(c.email)}</div></td>
      <td>${CONTACT_ROLES[c.role] || esc(c.role)}</td>
      <td class="cap">${c.last_sent ? `Emailed ${esc(c.last_sent.slice(0, 10))}` : "Not emailed"}</td>
      <td class="num">
        <button class="btn ghost" data-act="draft" data-id="${c.id}" ${busy || !aiEnabled ? "disabled" : ""}>
          ${busy === `draft:${c.id}` ? "Writing…" : "Draft email"}</button>
        <button class="link" data-act="remove-contact" data-id="${c.id}">Remove</button></td></tr>`).join("");
  return `<table class="grid">${rows}</table>`;
}

function sentTable(sent) {
  const rows = sent.map((i) => `<tr><td class="cap">${esc(i.sent.slice(0, 16))}<div>${i.via === "outlook-web" ? "Outlook web" : "Sent here"}</div></td>
      <td>${esc(i.company)}<div class="cap">${esc(i.email)}</div></td>
      <td><details><summary>${esc(i.subject)}</summary><p class="sent-body">${esc(i.body)}</p>
        ${i.attachments.length ? `<div class="cap">Attached: ${i.attachments.map(esc).join(", ")}</div>` : ""}</details></td></tr>`).join("");
  return `<table class="grid">${rows}</table>`;
}

/** The buyer, and each winner of an awarded tender: the companies a lead lets us introduce ourselves to. */
function introducePeople(lead) {
  const buyer = lead.buyer_en || lead.buyer;
  return [
    ...(buyer ? [{ company: buyer, role: "buyer", label: `Buyer: ${buyer}` }] : []),
    ...(lead.extra?.winners || []).map((w) => ({
      company: w.company_en || w.company, cr: w.cr || "", role: "partner", label: `Winner: ${w.company_en || w.company}`,
    })),
  ];
}

/** "Introduce us" in a lead's panel. */
function introduceBlock(lead) {
  const people = introducePeople(lead);
  if (!people.length) return "";
  const open = lead.status === "open" || lead.status === "future";
  return `<div class="block"><h4>Introduce us</h4>
      <p class="cap">Email an introduction with your company profile.${open ? " While this tender is open, the email to the buyer asks only to be invited to future tenders." : ""}</p>
      <div class="analyze-controls">${people.map((p, i) => `<button class="btn ghost" data-introduce="${i}" dir="auto">${esc(p.label)}</button>`).join("")}</div>
    </div>`;
}

function introducePrefill(lead, index) {
  const { company, cr = "", role } = introducePeople(lead)[index];
  return { company, cr, role, lead_key: lead.key };
}
