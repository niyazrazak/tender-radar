"use strict";

/** Detail panel for one lead, with the triage buttons. */
const drawer = {
  lead: null,
  showOriginal: false,
  analyzing: false,

  show(lead) {
    if (!lead) return;
    if (this.lead !== lead) this.showOriginal = false;
    this.lead = lead;
    this.refresh();
    $("drawer").classList.add("open");
    $("drawer").setAttribute("aria-hidden", "false");
    $("scrim").classList.add("open");
  },

  refresh() {
    const lead = this.lead;
    if (!lead) return;
    const translated = lead.title_en && lead.title_en !== lead.title;
    const brief = this.showOriginal ? lead.brief : lead.brief_en || lead.brief;
    const activities = this.showOriginal ? lead.activities : lead.activities_en || lead.activities;
    const hasOriginal = lead.brief_en && lead.brief_en !== lead.brief;
    $("drawerBody").innerHTML = `
      <div class="drawer-head">
        <span>${esc(SOURCE_LABELS[lead.source] || lead.source)} · score ${lead.score}</span>
        <button class="icon-btn" data-close aria-label="Close">
          <svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div>
        <h2 dir="auto">${esc(lead.title_en || lead.title)}</h2>
        ${translated ? `<div class="original" dir="rtl">${esc(lead.title)}</div>` : ""}
      </div>
      <div class="actions">
        <a class="btn primary" href="${esc(lead.url)}" target="_blank" rel="noopener">Open on portal
          <svg viewBox="0 0 20 20"><path d="M8 4H4v12h12v-4M11 3h6v6M17 3l-8 8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
        <div class="seg">${["shortlisted", "bidding", "dismissed"].map((s) =>
          `<button data-state="${s}" class="${lead.lead_status === s ? "on" : ""}">${STATE_LABELS[s]}</button>`).join("")}</div>
      </div>
      ${fitBlock(lead)}
      ${analysisBlock(lead, this.analyzing)}
      ${pitchBlock(lead, this.pitching)}
      ${teamBlock(lead)}
      <dl class="facts">${facts(lead)}</dl>
      ${bidsBlock(lead)}
      ${chips(lead.matched) ? `<div class="block"><h4>Matched keywords</h4>${chips(lead.matched)}</div>` : ""}
      ${activities ? `<div class="block"><h4>Activities</h4><p dir="auto">${esc(activities)}</p></div>` : ""}
      ${brief ? `<div class="block"><h4>Brief ${hasOriginal ? `<button class="toggle-lang" data-lang>${this.showOriginal ? "Show English" : "Show original"}</button>` : ""}</h4>
        <p dir="auto">${esc(brief)}</p></div>` : ""}`;
  },

  close() {
    $("drawer").classList.remove("open");
    $("drawer").setAttribute("aria-hidden", "true");
    $("scrim").classList.remove("open");
  },

  isOpen() {
    return $("drawer").classList.contains("open");
  },

  bind(app) {
    $("scrim").addEventListener("click", () => this.close());
    $("drawerBody").addEventListener("click", (e) => {
      if (e.target.closest("[data-close]")) this.close();
      const state = e.target.closest("[data-state]");
      if (state) app.setState(this.lead, state.dataset.state);
      if (e.target.closest("[data-lang]")) { this.showOriginal = !this.showOriginal; this.refresh(); }
      if (e.target.closest("[data-analyze]")) this.analyze([]);
      if (e.target.closest("[data-save-team]")) this.saveTeam(app);
      if (e.target.closest("[data-pitch]")) this.draftPitch();
      if (e.target.closest("[data-copy-pitch]")) this.copyPitch();
    });
    $("drawerBody").addEventListener("change", (e) => {
      if (e.target.matches("[data-upload]") && e.target.files.length) this.analyze([...e.target.files]);
    });
  },

  /** Asks Claude for a first message to the winner, offering the freelancer's services. */
  async draftPitch() {
    const lead = this.lead;
    this.pitching = true;
    this.refresh();
    try {
      const result = await api.post("/api/pitch", { key: lead.key });
      if (!result.ok) throw new Error(result.data.error);
      lead.pitch = result.data.pitch;
    } catch (error) {
      toast(`Pitch failed: ${error.message}`);
    } finally {
      this.pitching = false;
      if (this.lead === lead) this.refresh();
    }
  },

  async copyPitch() {
    const pitch = this.lead.pitch;
    await navigator.clipboard.writeText(`${pitch.subject}\n\n${pitch.message}`);
    toast("Pitch copied");
  },

  async saveTeam(app) {
    const form = $("drawerBody");
    const fields = {
      owner: form.querySelector("[name=owner]").value,
      bid_due: form.querySelector("[name=bid_due]").value,
      notes: form.querySelector("[name=notes]").value,
    };
    if (await app.saveTeamFields(this.lead, fields)) toast("Saved");
  },

  /** Uploads tender documents (if any) and asks Claude for a bid / no-bid analysis. */
  async analyze(files) {
    const lead = this.lead;
    this.analyzing = true;
    this.refresh();
    try {
      const uploads = await Promise.all(files.map(async (file) => ({ name: file.name, data: await toBase64(file) })));
      const result = await api.post("/api/analyze", { key: lead.key, files: uploads });
      if (!result.ok) throw new Error(result.data.error);
      lead.ai_analysis = result.data.analysis;
    } catch (error) {
      toast(`Analysis failed: ${error.message}`);
    } finally {
      this.analyzing = false;
      if (this.lead === lead) this.refresh();
    }
  },
};

function fitBlock(lead) {
  if (lead.ai_fit === null || lead.ai_fit === undefined) return "";
  return `<div class="block"><h4>AI fit</h4><p>${fitBadge(lead)} ${esc(lead.ai_reason)}</p></div>`;
}

const VERDICTS = { bid: ["Bid", "good"], consider: ["Consider", "soon"], "no-bid": ["No bid", "urgent"] };

function analysisBlock(lead, busy) {
  const a = lead.ai_analysis;
  const off = !app.aiEnabled;
  const controls = `<div class="analyze-controls">
      <button class="btn ${a ? "ghost" : "primary"}" data-analyze ${busy || off ? "disabled" : ""}>${a ? "Analyze again" : "Analyze tender"}</button>
      <label class="btn ghost ${busy || off ? "disabled" : ""}" title="PDF or text files of the tender documents">Upload documents…
        <input type="file" data-upload multiple accept=".pdf,.txt,.md" hidden ${busy || off ? "disabled" : ""}></label>
      ${busy ? '<span class="busy">Claude is reading the tender… this can take a minute or two.</span>' : ""}
      ${off ? '<span class="busy">Log in to Claude Code (run claude in a terminal) or set ANTHROPIC_API_KEY, then restart the service to turn on AI analysis.</span>' : ""}
    </div>`;
  if (!a) return `<div class="block"><h4>Bid / no-bid</h4>${controls}</div>`;
  const [label, tone] = VERDICTS[a.recommendation] || [a.recommendation, ""];
  const list = (title, items) => (items && items.length
    ? `<h5>${title}</h5><ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "");
  return `<div class="block analysis"><h4>Bid / no-bid</h4>
      <div class="verdict ${tone}">${esc(label)}</div>
      <p>${esc(a.reasoning)}</p>
      <p class="summary">${esc(a.summary)}</p>
      ${list("Scope", a.scope)}${list("Requirements", a.requirements)}${list("Key dates", a.key_dates)}
      ${list("Risks", a.risks)}${list("Questions for the buyer", a.questions)}
      <div class="cap">${a.documents_read && a.documents?.length ? `Read ${a.documents.map(esc).join(", ")}` : "From the portal details only. Upload the tender documents for a full analysis."}</div>
      ${controls}</div>`;
}

function pitchBlock(lead, busy) {
  const winners = lead.extra?.winners || [];
  if (lead.status !== "awarded" || !winners.length) return "";
  const off = !app.aiEnabled;
  const who = winners.map((w) => `<div><b dir="auto">${esc(w.company)}</b>${w.cr ? ` <span class="cap">CR ${esc(w.cr)}</span>` : ""}
      ${w.value ? ` <span class="cap">· ${esc(w.value)} ${esc(lead.currency)}</span>` : ""}</div>`).join("");
  const p = lead.pitch;
  const draft = p ? `<div class="pitch"><div class="cap">Subject</div><p>${esc(p.subject)}</p>
      <div class="cap">Message</div><p>${esc(p.message)}</p>
      ${p.work_to_offer?.length ? `<div class="cap">Work you could offer</div><ul>${p.work_to_offer.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <button class="btn ghost" data-copy-pitch>Copy</button></div>` : "";
  return `<div class="block analysis"><h4>Pitch the winner</h4>
      <p class="cap">The winner may need help to deliver. Offer to take on part of the work as a subcontractor.
        Look the company up by its commercial registration (CR) number to find a contact.</p>
      ${who}${draft}
      <div class="analyze-controls">
        <button class="btn ${p ? "ghost" : "primary"}" data-pitch ${busy || off ? "disabled" : ""}>${p ? "Draft again" : "Draft a pitch"}</button>
        ${busy ? '<span class="busy">Claude is writing…</span>' : ""}
        ${off ? '<span class="busy">Log in to Claude Code (run claude in a terminal) or set ANTHROPIC_API_KEY, then restart the service to draft pitches.</span>' : ""}
      </div></div>`;
}

function teamBlock(lead) {
  return `<div class="block team"><h4>Team</h4>
      <div class="team-row">
        <label>Owner<input name="owner" value="${esc(lead.owner)}" placeholder="Who prepares the bid"></label>
        <label>Our bid deadline<input name="bid_due" type="date" value="${esc(lead.bid_due)}"></label>
      </div>
      <label>Notes<textarea name="notes" rows="3" placeholder="Partner, pricing, questions…">${esc(lead.notes)}</textarea></label>
      <div><button class="btn ghost" data-save-team>Save</button></div></div>`;
}

function bidsBlock(lead) {
  const bids = lead.extra?.bids || [];
  if (!bids.length) return "";
  const rows = bids.map((bid) => `<tr class="${bid.note.includes("مستبعد") ? "excluded" : ""}">
      <td dir="auto">${esc(bid.company)}</td><td class="num">${esc(bid.value)}</td><td dir="auto">${esc(bid.result)}</td></tr>`).join("");
  return `<div class="block"><h4>Bids</h4><table class="bids"><tr><th>Company</th><th>Bid (${esc(lead.currency)})</th><th>Result</th></tr>${rows}</table></div>`;
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** Market intelligence: who wins tenders like ours, which buyers buy them, at what price. */
const market = {
  isOpen() {
    return !$("market").hidden;
  },

  async toggle() {
    if (this.isOpen()) return this.close();
    $("market").hidden = false;
    $("marketBody").innerHTML = '<div class="note">Loading…</div>';
    try {
      this.render(await api.get("/api/market"));
    } catch (error) {
      $("marketBody").innerHTML = `<div class="note">Could not load: ${esc(error.message)}</div>`;
    }
  },

  close() {
    $("market").hidden = true;
  },

  render(data) {
    const money = (n, currency = "QAR") => (n ? `${Math.round(n).toLocaleString("en-US")} ${currency}` : "—");
    const competitors = data.competitors.map((c) => `<tr>
        <td dir="auto">${esc(c.company)}</td><td class="num">${c.relevant_wins}</td><td class="num">${c.wins}</td>
        <td class="num">${c.bids}</td><td class="num">${c.win_rate === null ? "—" : `${Math.round(c.win_rate * 100)}%`}</td>
        <td class="num">${money(c.won_value)}</td></tr>`).join("");
    const partners = (data.partners || []).map((p) => `<tr>
        <td dir="auto">${esc(p.company)}</td><td class="num">${p.relevant_wins}</td>
        <td class="num">${money(p.relevant_value, p.currency)}</td>
        <td dir="auto">${p.largest ? `${esc(p.largest.title)} <span class="cap">${money(p.largest.value, p.currency)}</span>` : ""}</td>
        <td dir="auto" class="cap">${esc(p.buyers.join("; "))}</td></tr>`).join("");
    const buyers = data.buyers.map((b) => `<tr><td dir="auto">${esc(b.buyer)}</td>
        <td class="num">${b.relevant}</td><td class="num">${b.awards}</td><td class="num">${money(b.value, b.currency)}</td></tr>`).join("");
    const recent = data.recent.map((r) => `<tr>
        <td><a href="${esc(r.url)}" target="_blank" rel="noopener" dir="auto">${esc(r.title)}</a><div class="cap" dir="auto">${esc(r.buyer)}</div></td>
        <td dir="auto">${esc(r.winners.join("; "))}</td><td class="num">${money(r.value, r.currency)}</td>
        <td class="num">${r.bidders || "—"}</td>
        <td class="num">${r.lowest_bid ? `${money(r.lowest_bid, "")} – ${money(r.highest_bid, "")}` : "—"}</td></tr>`).join("");
    const empty = !data.awarded
      ? `<div class="note">No award reports yet (${data.awarded_total} awarded tenders stored). Run
         <code>.venv/bin/python -m tender_radar backfill-awards</code> to read their reports, or wait for the next checks.</div>`
      : "";
    $("marketBody").innerHTML = `
      <div class="drawer-head"><span>Market · ${data.awarded} award reports · ${data.relevant_awarded} in your field</span>
        <button class="icon-btn" data-close-market aria-label="Close">
          <svg viewBox="0 0 20 20"><path d="m5 5 10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button></div>
      ${empty}
      <h3>Competitors</h3><p class="cap">"In your field" counts tenders that match your keywords or AI fit.</p>
      <table class="grid"><tr><th>Company</th><th>Wins in your field</th><th>All wins</th><th>Bids</th><th>Win rate</th><th>Won value</th></tr>${competitors}</table>
      <h3>Partners to approach</h3>
      <p class="cap">Companies that win larger contracts in your field. A small company can offer to deliver the software part
        as their subcontractor: they hold the bond and the registration.</p>
      <table class="grid"><tr><th>Company</th><th>Wins in your field</th><th>Value in your field</th><th>Largest win</th><th>Buyers</th></tr>${partners || '<tr><td colspan="5" class="cap">None yet.</td></tr>'}</table>
      <h3>Buyers</h3>
      <table class="grid"><tr><th>Buyer</th><th>Awards in your field</th><th>All awards</th><th>Awarded value</th></tr>${buyers}</table>
      <h3>Recent awards in your field</h3>
      <table class="grid"><tr><th>Tender</th><th>Winner</th><th>Award</th><th>Bidders</th><th>Bid range</th></tr>${recent}</table>`;
  },

  bind() {
    $("market").addEventListener("click", (e) => {
      if (e.target === $("market") || e.target.closest("[data-close-market]")) this.close();
    });
  },
};

function upfrontFact(lead) {
  const usd = lead.small?.upfront_usd;
  if (usd === null || usd === undefined) return "Unknown (bond as % of bid, or fee or bond not listed)";
  return `${fmtUSD(usd)} <span class="cap">document fee + bid bond. The bond is a bank guarantee, returned if you do not win.</span>`;
}

function smallFact(lead) {
  const small = lead.small || {};
  const notes = [];
  if (small.sme_reserved) notes.push("Reserved for small and medium enterprises.");
  if (small.small_value) notes.push(`${esc(small.small_value)}: usually a small bond or none.`);
  if (lead.country === "Qatar") {
    notes.push("Qatar: SMEs rated and accredited by Qatar Development Bank can be exempt from the bid bond, "
      + "and document fees are waived below set limits. Check the current limits with QDB or the Ministry of Finance.");
  }
  return notes.map((note) => `<div>${note}</div>`).join("");
}

function facts(lead) {
  const left = daysLeft(lead.closing, todayISO());
  const money = (value) => (value ? `${esc(value)} ${esc(lead.currency)}` : "");
  const rows = [
    ["Buyer", `<span dir="auto">${esc(lead.buyer_en || lead.buyer)}</span>`],
    ["Country", esc(lead.country)],
    ["Reference", esc(lead.ref_no)],
    ["Status", esc(lead.status)],
    ["Type", esc(lead.tender_type)],
    ["Category", `<span dir="auto">${esc(lead.category_en || lead.category)}</span>`],
    // For awarded tenders the portal's date is the award date.
    [lead.status === "awarded" ? "Awarded" : "Published", lead.published ? fmtDate(lead.published) : ""],
    ["Closing", lead.closing ? `${fmtDate(lead.closing)}${left !== null && left >= 0 ? ` · ${left} days left` : ""}` : ""],
    ["Document fee", esc(fmtFee(lead)) || "Not listed"],
    ["Bid bond", esc(fmtBond(lead)) || "Not listed"],
    ["Up-front cost", upfrontFact(lead)],
    ["Small company", smallFact(lead)],
    ["Winner", `<span dir="auto">${esc((lead.extra?.winners || []).map((w) => w.company).join("; "))}</span>`],
    ["Award value", money(lead.extra?.award_value)],
    ["Bidders", lead.extra?.bidders ? esc(lead.extra.bidders) : ""],
    ["First seen", esc(lead.first_seen.slice(0, 10))],
  ];
  return rows.filter(([, v]) => v && v !== "<span dir=\"auto\"></span>")
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

/** The status dot in the header and the "recent checks" popover. */
const runPanel = {
  status: null,

  update(status) {
    this.status = status;
    const sched = status.scheduler;
    const last = status.runs.find((r) => r.status !== "running");
    $("runNow").disabled = sched.running;
    $("runDot").className = `dot ${sched.running ? "running" : last ? last.status : ""}`;
    $("runText").textContent = sched.running
      ? `Checking portals… ${ago(sched.running_since, true)}`
      : last ? `Checked ${ago(last.finished)} · next ${clock(sched.next_run)}` : `First check ${clock(sched.next_run)}`;
    if (!$("activity").hidden) this.render();
  },

  offline() {
    $("runDot").className = "dot error";
    $("runText").textContent = "Server not reachable";
  },

  async runNow() {
    const result = await api.post("/api/run", {});
    toast(result.ok ? "Checking all portals. New leads appear when it finishes." : "A check is already running.");
    app.poll();
  },

  toggle() {
    $("activity").hidden = !$("activity").hidden;
    if (!$("activity").hidden) this.render();
  },

  close() {
    $("activity").hidden = true;
  },

  render() {
    const status = this.status;
    if (!status) return;
    const runs = status.runs.map((run) => `
      <div class="run"><span class="dot ${run.status}"></span><div class="run-main">
        <div class="run-title">${run.status === "running" ? "Running" : `${run.new_count} new of ${run.total}`}
          <span>${when(run.started)} · ${run.trigger}</span></div>
        <div class="run-sources">${Object.entries(run.sources).map(([name, s]) => s.ok
          ? `${esc(SOURCE_LABELS[name] || name)} ${s.count}`
          : `<span class="fail" title="${esc(s.error)}">${esc(SOURCE_LABELS[name] || name)} failed</span>`).join(" · ")}
          ${run.error ? `<span class="fail">${esc(run.error)}</span>` : ""}</div>
      </div></div>`).join("");
    const hours = status.scheduler.interval_hours;
    $("activity").innerHTML = `<h3>Recent checks</h3>${runs || '<div class="note">No checks yet.</div>'}
      <div class="note">Checks every ${hours} hours while this computer is awake. A check missed during sleep runs on wake.</div>`;
  },
};

/** Floating display settings, saved in the browser. */
const tweaks = {
  bind(app) {
    $("tweaksToggle").addEventListener("click", () => { $("tweaksPanel").hidden = !$("tweaksPanel").hidden; this.render(app); });
    $("tweaksPanel").addEventListener("click", (e) => {
      const option = e.target.closest("[data-pref]");
      if (!option) return;
      app.prefs[option.dataset.pref] = option.dataset.value;
      app.applyPrefs();
      app.render();
      this.render(app);
    });
    drawer.bind(app);
    market.bind();
  },

  render(app) {
    $("tweaksPanel").innerHTML = Object.entries(TWEAKS).map(([key, tweak]) => `
      <div class="tweak">${tweak.label}<div class="seg">${tweak.options.map(([value, label]) =>
        `<button data-pref="${key}" data-value="${value}" class="${app.prefs[key] === value ? "on" : ""}">${label}</button>`).join("")}</div></div>`
    ).join("");
  },
};

/* Time formatting: the server stores UTC as "YYYY-MM-DD HH:MM:SS". */

function utc(text) {
  return new Date(`${text.replace(" ", "T")}Z`);
}

function ago(text, short = false) {
  const minutes = Math.max(0, Math.round((Date.now() - utc(text)) / 60000));
  if (minutes < 1) return short ? "just started" : "just now";
  if (minutes < 60) return `${minutes} min${short ? "" : " ago"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h${short ? "" : " ago"}`;
  return `${Math.round(hours / 24)} days ago`;
}

function clock(text) {
  const d = utc(text);
  if (d <= new Date()) return "soon";
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return sameDay ? time : `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

function when(text) {
  return utc(text).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const app = new Dashboard();
app.start();
