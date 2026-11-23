"use strict";

/* Company profile: the details and documents that introduce the company to buyers and partners.
   Claude rates tenders against it. Documents marked "Attach" go with introduction emails. */

const PROFILE_SECTIONS = [
  ["Company", [
    ["name", "Trading name"], ["legal_name", "Legal name"], ["cr_number", "Commercial registration (CR)"],
    ["established", "Established"], ["employees", "Employees"], ["website", "Website"],
  ]],
  ["Contact", [
    ["contact_name", "Contact person"], ["contact_title", "Job title"], ["email", "Email"],
    ["phone", "Phone"], ["address", "Address", "wide"],
  ]],
  ["What you do", [
    ["about", "About the company", "text"],
    ["services", "Services and products", "list"],
    ["sectors", "Sectors you serve", "list"],
    ["certifications", "Certifications and partnerships", "list"],
    ["clients", "Clients and projects", "list"],
    ["differentiators", "Why choose you", "text"],
  ]],
  ["Introduction emails", [
    ["signature", "Email signature", "text"],
  ]],
];
const DOCUMENT_KINDS = {
  profile: "Company profile", cr: "Commercial registration", license: "Trade license",
  certificate: "Certificate", other: "Other",
};
const LIST_HINT = "One per line";

const company = {
  data: null,
  busy: "",  // "", "upload", "read" or "save"

  isOpen() {
    return !$("companyPanel").hidden;
  },

  async toggle() {
    if (this.isOpen()) return this.close();
    $("companyPanel").hidden = false;
    $("companyBody").innerHTML = '<div class="note">Loading…</div>';
    try {
      this.data = await api.get("/api/company");
      this.render();
    } catch (error) {
      $("companyBody").innerHTML = `<div class="note">Could not load: ${esc(error.message)}</div>`;
    }
  },

  close() {
    $("companyPanel").hidden = true;
  },

  render() {
    const { details, documents, saved, ai_enabled: aiEnabled } = this.data;
    const sections = PROFILE_SECTIONS.map(([title, fields]) => `
      <h3>${title}</h3>
      ${title === "Introduction emails" ? `<p class="cap">Later, Tender Radar will email buyers and partners to introduce
        you. It will sign with this, and attach the documents marked <b>Attach</b> below.</p>` : ""}
      <div class="profile-grid">${fields.map((field) => profileField(field, details, this.data.fallback)).join("")}</div>`).join("");
    $("companyBody").innerHTML = `
      <div class="drawer-head"><span>Company profile${saved ? "" : " · not saved yet"}</span>
        <button class="icon-btn" data-close-company aria-label="Close">
          <svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button></div>
      <p class="cap">Claude rates and analyzes tenders against this profile. Tenders already rated keep their rating.</p>
      ${documentsBlock(documents, aiEnabled, this.busy)}
      <form id="profileForm">${sections}
        <div class="analyze-controls">
          <button class="btn primary" type="submit" ${this.busy ? "disabled" : ""}>Save profile</button>
          ${this.busy === "save" ? '<span class="busy">Saving…</span>' : ""}
        </div>
      </form>`;
  },

  bind() {
    const panel = $("companyPanel");
    panel.addEventListener("click", (e) => {
      if (e.target === panel || e.target.closest("[data-close-company]")) this.close();
      const remove = e.target.closest("[data-remove-doc]");
      if (remove) this.updateDocument({ name: remove.dataset.removeDoc, remove: true });
      if (e.target.closest("[data-read-docs]")) this.readDocuments();
    });
    panel.addEventListener("change", (e) => {
      if (e.target.matches("[data-company-upload]") && e.target.files.length) this.upload([...e.target.files]);
      if (e.target.matches("[data-doc-kind]")) this.updateDocument({ name: e.target.dataset.docKind, kind: e.target.value });
      if (e.target.matches("[data-doc-attach]")) {
        this.updateDocument({ name: e.target.dataset.docAttach, attach: e.target.checked });
      }
    });
    panel.addEventListener("submit", (e) => { e.preventDefault(); this.save(); });
  },

  /** The form's values. Unsaved edits survive a re-render through this. */
  formDetails() {
    const form = $("profileForm");
    const details = { ...this.data.details };
    for (const element of form.querySelectorAll("[name]")) {
      details[element.name] = element.dataset.list !== undefined
        ? element.value.split("\n").map((line) => line.trim()).filter(Boolean) : element.value.trim();
    }
    return details;
  },

  async save() {
    const details = this.formDetails();
    await this.request("save", "/api/company", { details }, "Profile saved");
  },

  async upload(files) {
    this.data.details = this.formDetails();
    const uploads = await Promise.all(files.map(async (file) => ({ name: file.name, data: await toBase64(file) })));
    await this.request("upload", "/api/company-upload", { files: uploads }, `${files.length} document${files.length > 1 ? "s" : ""} added`);
  },

  async updateDocument(change) {
    this.data.details = this.formDetails();
    await this.request("", "/api/company-document", change);
  },

  /** Claude reads the documents and fills the empty fields. Nothing is saved until the user saves. */
  async readDocuments() {
    this.data.details = this.formDetails();
    this.busy = "read";
    this.render();
    try {
      const result = await api.post("/api/company-read", {});
      if (!result.ok) throw new Error(result.data.error);
      const filled = fillEmpty(this.data.details, result.data.details);
      toast(filled ? `Filled ${filled} field${filled > 1 ? "s" : ""}. Check them, then save.` : "Nothing new found in the documents");
    } catch (error) {
      toast(`Could not read the documents: ${error.message}`);
    } finally {
      this.busy = "";
      this.render();
    }
  },

  /** Posts a change. The server answers with the whole profile; unsaved form edits are kept. */
  async request(busy, path, body, done = "") {
    const unsaved = this.data.details;
    this.busy = busy;
    if (busy) this.render();
    try {
      const result = await api.post(path, body);
      if (!result.ok) throw new Error(result.data.error);
      const keep = path === "/api/company" ? result.data.details : unsaved;
      this.data = { ...this.data, ...result.data, details: keep };
      if (path === "/api/company") app.poll();  // the sidebar shows the company name
      if (done) toast(done);
    } catch (error) {
      toast(`Could not save: ${error.message}`);
    } finally {
      this.busy = "";
      this.render();
    }
  },
};

function profileField([name, label, kind], details, fallback) {
  const value = details[name];
  if (kind === "list") {
    const text = (value || []).join("\n");
    return `<label class="wide">${label} <span class="cap">${LIST_HINT}</span>
      <textarea name="${name}" data-list rows="${Math.max(3, (value || []).length + 1)}">${esc(text)}</textarea></label>`;
  }
  if (kind === "text") {
    // Until "about" is filled in, Claude uses the line in config.json -> "company".
    const placeholder = name === "about" && fallback ? ` placeholder="${esc(fallback)}"` : "";
    return `<label class="wide">${label}<textarea name="${name}" rows="4"${placeholder}>${esc(value)}</textarea></label>`;
  }
  return `<label class="${kind || ""}">${label}<input name="${name}" value="${esc(value)}"></label>`;
}

function documentsBlock(documents, aiEnabled, busy) {
  const rows = documents.map((doc) => `<tr>
      <td><a href="/api/company-document?name=${encodeURIComponent(doc.name)}" target="_blank" rel="noopener">${esc(doc.name)}</a>
        <div class="cap">${fileSize(doc.size)} · added ${esc(doc.added)}</div></td>
      <td><select data-doc-kind="${esc(doc.name)}">${Object.entries(DOCUMENT_KINDS).map(([value, label]) =>
        `<option value="${value}" ${doc.kind === value ? "selected" : ""}>${label}</option>`).join("")}</select></td>
      <td><label class="check"><input type="checkbox" data-doc-attach="${esc(doc.name)}" ${doc.attach ? "checked" : ""}> Attach</label></td>
      <td class="num"><button class="link" data-remove-doc="${esc(doc.name)}">Remove</button></td></tr>`).join("");
  const readable = documents.some((doc) => /\.(pdf|png|jpe?g)$/i.test(doc.name));
  return `<h3>Documents</h3>
    <p class="cap">Your company profile PDF, CR copy, trade license and certificates. PDF, image or Word files.</p>
    ${documents.length ? `<table class="grid">${rows}</table>` : ""}
    <div class="analyze-controls">
      <label class="btn ghost ${busy ? "disabled" : ""}">Upload documents…
        <input type="file" data-company-upload multiple accept=".pdf,.png,.jpg,.jpeg,.docx" hidden ${busy ? "disabled" : ""}></label>
      <button class="btn ${readable ? "primary" : "ghost"}" data-read-docs ${busy || !aiEnabled || !readable ? "disabled" : ""}
        title="Claude reads the PDFs and images and fills the empty fields below">Fill from documents</button>
      ${busy === "upload" ? '<span class="busy">Uploading…</span>' : ""}
      ${busy === "read" ? '<span class="busy">Claude is reading your documents… this can take a minute.</span>' : ""}
      ${!aiEnabled ? '<span class="busy">AI is off, so fill the form by hand.</span>' : ""}
    </div>`;
}

/** Copies found values into empty fields only, so nothing the user typed is lost. Returns how many it filled. */
function fillEmpty(details, found) {
  let filled = 0;
  for (const [name, value] of Object.entries(found || {})) {
    const empty = Array.isArray(details[name]) ? !details[name].length : !String(details[name] || "").trim();
    const given = Array.isArray(value) ? value.length : String(value || "").trim();
    if (empty && given) { details[name] = value; filled += 1; }
  }
  return filled;
}

function fileSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
